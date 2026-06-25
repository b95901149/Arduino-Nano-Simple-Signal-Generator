/*
 * Arduino Nano AND Gate Tester (ATmega328P) — Master
 * D2/D3 = waveform, D5-D8 = inputs, D9/D12/D13 = GPIO outputs
 * D10/D11 = SoftwareSerial to slave (RX=10, TX=11)
 * USB Serial @ 115200 baud
 */

#include <Arduino.h>
#include <SoftwareSerial.h>
#include <avr/interrupt.h>
#include <avr/io.h>
#include <string.h>

#define PIN_A_BIT PD2
#define PIN_B_BIT PD3
#define PIN_A_MASK (1 << PIN_A_BIT)
#define PIN_B_MASK (1 << PIN_B_BIT)

static const uint8_t SS_RX_PIN = 10;
static const uint8_t SS_TX_PIN = 11;
static const uint32_t SS_BAUD = 9600;
static const uint32_t SS_TIMEOUT_MS = 500UL;

static const uint8_t INPUT_PINS[] = {5, 6, 7, 8};
static const uint8_t OUTPUT_PINS[] = {9, 12, 13};

static SoftwareSerial g_softSerial(SS_RX_PIN, SS_TX_PIN);

static const uint32_t MAX_ISR_HZ = 80000UL;
static const uint32_t MIN_FREQ_HZ = 10UL;
static const uint32_t MAX_FREQ_HZ = 80000UL;

volatile uint32_t g_freq_hz = 20000UL;
volatile uint16_t g_phase_deg = 0;
volatile uint8_t g_running = 0;

volatile uint16_t g_steps_per_cycle = 4;
volatile uint16_t g_half_cycle = 2;
volatile uint16_t g_phase_offset = 0;
volatile uint16_t g_position = 0;

char g_rx_buf[80];
uint8_t g_rx_len = 0;

static inline void pinsLow(void) {
  PORTD &= ~(PIN_A_MASK | PIN_B_MASK);
}

static void detachTimer2Pwm(void) {
  TCCR2A &= (uint8_t)~((1 << COM2A1) | (1 << COM2A0) | (1 << COM2B1) | (1 << COM2B0));
  TCCR2B = 0;
  TCNT2 = 0;
  OCR2A = 0;
  OCR2B = 0;
}

static void ssInit(void) {
  g_softSerial.begin(SS_BAUD);
}

static bool readSoftSerialLine(char *buf, size_t cap) {
  size_t len = 0;
  uint32_t start = millis();
  while (millis() - start < SS_TIMEOUT_MS) {
    while (g_softSerial.available() > 0) {
      char c = (char)g_softSerial.read();
      if (c == '\n' || c == '\r') {
        if (len > 0) {
          buf[len] = '\0';
          return true;
        }
      } else if (len < cap - 1) {
        buf[len++] = c;
      }
    }
  }
  if (len > 0) {
    buf[len] = '\0';
    return true;
  }
  return false;
}

static void sendSsDiag(void) {
  Serial.print(F("SSDIAG:RX=D"));
  Serial.print(SS_RX_PIN);
  Serial.print(F(",TX=D"));
  Serial.print(SS_TX_PIN);
  Serial.print(F(",BAUD="));
  Serial.print(SS_BAUD);
  Serial.print(F(",AVAIL="));
  Serial.println(g_softSerial.available());
}

static void forwardToSlave(const char *cmd) {
  while (g_softSerial.available() > 0) {
    (void)g_softSerial.read();
  }
  g_softSerial.print(cmd);
  g_softSerial.print('\n');

  char resp[80];
  if (readSoftSerialLine(resp, sizeof(resp))) {
    Serial.print(F("SSR:"));
    Serial.println(resp);
  } else {
    Serial.println(F("ERR:SS_TIMEOUT"));
  }
}

static void gpioInit(void) {
  pinMode(2, OUTPUT);
  pinMode(3, OUTPUT);
  detachTimer2Pwm();
  pinsLow();

  for (uint8_t i = 0; i < 4; i++) {
    pinMode(INPUT_PINS[i], INPUT);
  }

  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }

  ssInit();
}

static uint16_t calcStepsPerCycle(uint32_t freq_hz) {
  if (freq_hz == 0) {
    return 2;
  }
  uint32_t steps = MAX_ISR_HZ / freq_hz;
  if (steps < 2) {
    steps = 2;
  }
  if (steps > 360) {
    steps = 360;
  }
  return (uint16_t)steps;
}

static uint16_t calcPhaseOffset(uint16_t phase_deg, uint16_t steps) {
  uint32_t offset = ((uint32_t)phase_deg * steps) / 360UL;
  return (uint16_t)(offset % steps);
}

static void applyWaveformParams(void) {
  uint16_t steps = calcStepsPerCycle(g_freq_hz);
  g_steps_per_cycle = steps;
  g_half_cycle = steps / 2;
  if (g_half_cycle < 1) {
    g_half_cycle = 1;
  }
  g_phase_offset = calcPhaseOffset(g_phase_deg, steps);
  g_position = 0;
}

static bool selectTimerPrescaler(uint32_t isr_hz, uint16_t *ocr, uint8_t *cs_bits) {
  const uint16_t prescalers[] = {1, 8, 64, 256, 1024};
  const uint8_t cs[] = {0b001, 0b010, 0b011, 0b100, 0b101};

  for (uint8_t i = 0; i < 5; i++) {
    uint32_t top = (F_CPU / prescalers[i]) / isr_hz;
    if (top >= 2UL && top <= 65536UL) {
      *ocr = (uint16_t)(top - 1UL);
      *cs_bits = cs[i];
      return true;
    }
  }
  return false;
}

static bool configureTimer(void) {
  applyWaveformParams();

  uint32_t isr_hz = g_freq_hz * (uint32_t)g_steps_per_cycle;
  uint16_t ocr;
  uint8_t cs_bits;

  if (!selectTimerPrescaler(isr_hz, &ocr, &cs_bits)) {
    return false;
  }

  uint8_t sreg = SREG;
  cli();
  TIMSK1 &= ~(1 << OCIE1A);
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1 = 0;
  OCR1A = ocr;
  TCCR1B = (1 << WGM12) | cs_bits;
  SREG = sreg;
  return true;
}

static void haltOutput(void) {
  uint8_t sreg = SREG;
  cli();
  g_running = 0;
  TIMSK1 &= ~(1 << OCIE1A);
  TCCR1B &= (uint8_t)~0b111;
  detachTimer2Pwm();
  pinsLow();
  g_position = 0;
  SREG = sreg;
}

static void startOutput(void) {
  if (!configureTimer()) {
    return;
  }

  uint8_t sreg = SREG;
  cli();
  g_position = 0;
  detachTimer2Pwm();
  g_running = 1;
  TIMSK1 |= (1 << OCIE1A);
  SREG = sreg;
}

static void sendStatus(void) {
  Serial.print(F("STATUS:FREQ="));
  Serial.print(g_freq_hz);
  Serial.print(F(",PHASE="));
  Serial.print(g_phase_deg);
  Serial.print(F(",RUN="));
  Serial.print(g_running);
  Serial.print(F(",STEPS="));
  Serial.println(g_steps_per_cycle);
}

static void sendInputs(void) {
  Serial.print(F("IN:D5="));
  Serial.print(digitalRead(5));
  Serial.print(F(",D6="));
  Serial.print(digitalRead(6));
  Serial.print(F(",D7="));
  Serial.print(digitalRead(7));
  Serial.print(F(",D8="));
  Serial.println(digitalRead(8));
}

static void sendOutputs(void) {
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    Serial.print(F("D"));
    Serial.print(pin);
    Serial.print(F("="));
    Serial.print(digitalRead(pin));
    if (i < 2) {
      Serial.print(F(","));
    }
  }
  Serial.println();
}

static bool parseUint(const char *s, uint32_t *out) {
  if (*s == '\0') {
    return false;
  }
  uint32_t val = 0;
  while (*s >= '0' && *s <= '9') {
    val = val * 10UL + (uint32_t)(*s - '0');
    s++;
  }
  if (*s != '\0') {
    return false;
  }
  *out = val;
  return true;
}

static bool isOutputPin(uint8_t pin) {
  for (uint8_t i = 0; i < 3; i++) {
    if (OUTPUT_PINS[i] == pin) {
      return true;
    }
  }
  return false;
}

static bool setUserOutput(uint8_t pin, uint8_t level) {
  if (!isOutputPin(pin)) {
    return false;
  }
  digitalWrite(pin, level ? HIGH : LOW);
  return true;
}

static void handleCommand(char *line) {
  if (strcmp(line, "START") == 0) {
    startOutput();
    Serial.println(g_running ? F("OK") : F("ERR:TIMER"));
    return;
  }

  if (strcmp(line, "STOP") == 0) {
    haltOutput();
    Serial.println(F("OK"));
    return;
  }

  if (strcmp(line, "STATUS?") == 0) {
    sendStatus();
    return;
  }

  if (strcmp(line, "IN?") == 0) {
    sendInputs();
    return;
  }

  if (strcmp(line, "OUT?") == 0) {
    Serial.print(F("OUT:"));
    sendOutputs();
    return;
  }

  if (strncmp(line, "OUT:", 4) == 0) {
    const char *args = line + 4;
    if (*args == 'D' || *args == 'd') {
      args++;
    }

    uint32_t pin;
    uint32_t level;
    const char *sep = strchr(args, ':');
    if (sep == NULL) {
      Serial.println(F("ERR:OUT_FORMAT"));
      return;
    }

    char pin_buf[8];
    uint8_t pin_len = (uint8_t)(sep - args);
    if (pin_len >= sizeof(pin_buf)) {
      Serial.println(F("ERR:OUT_PIN"));
      return;
    }
    memcpy(pin_buf, args, pin_len);
    pin_buf[pin_len] = '\0';

    if (!parseUint(pin_buf, &pin) || !parseUint(sep + 1, &level) || level > 1UL) {
      Serial.println(F("ERR:OUT_FORMAT"));
      return;
    }

    if (!setUserOutput((uint8_t)pin, (uint8_t)level)) {
      Serial.println(F("ERR:OUT_PIN"));
      return;
    }

    Serial.println(F("OK"));
    return;
  }

  if (strncmp(line, "FREQ:", 5) == 0) {
    uint32_t hz;
    if (!parseUint(line + 5, &hz) || hz < MIN_FREQ_HZ || hz > MAX_FREQ_HZ) {
      Serial.println(F("ERR:FREQ_RANGE"));
      return;
    }

    uint8_t was_running = g_running;
    if (was_running) {
      haltOutput();
    }

    g_freq_hz = hz;
    if (!configureTimer()) {
      Serial.println(F("ERR:TIMER"));
      return;
    }

    if (was_running) {
      startOutput();
    }
    Serial.println(F("OK"));
    return;
  }

  if (strncmp(line, "PHASE:", 6) == 0) {
    uint32_t deg;
    if (!parseUint(line + 6, &deg) || deg > 360UL) {
      Serial.println(F("ERR:PHASE_RANGE"));
      return;
    }

    g_phase_deg = (uint16_t)deg;
    g_phase_offset = calcPhaseOffset(g_phase_deg, g_steps_per_cycle);
    Serial.println(F("OK"));
    return;
  }

  if (strcmp(line, "SSDIAG?") == 0) {
    sendSsDiag();
    return;
  }

  if (strncmp(line, "SS:", 3) == 0) {
    if (line[3] == '\0') {
      Serial.println(F("ERR:SS_EMPTY"));
      return;
    }
    forwardToSlave(line + 3);
    return;
  }

  Serial.println(F("ERR:UNKNOWN"));
}

ISR(TIMER1_COMPA_vect) {
  if (!g_running) {
    return;
  }

  uint16_t steps = g_steps_per_cycle;
  uint16_t half = g_half_cycle;
  uint16_t pos = g_position;

  if (pos < half) {
    PORTD |= PIN_A_MASK;
  } else {
    PORTD &= ~PIN_A_MASK;
  }

  uint16_t b_pos = pos + g_phase_offset;
  if (b_pos >= steps) {
    b_pos -= steps;
  }

  if (b_pos < half) {
    PORTD |= PIN_B_MASK;
  } else {
    PORTD &= ~PIN_B_MASK;
  }

  pos++;
  if (pos >= steps) {
    pos = 0;
  }
  g_position = pos;
}

void setup(void) {
  gpioInit();
  Serial.begin(115200);
  configureTimer();
  haltOutput();
  Serial.println(F("READY ANDGATE_TESTER"));
}

void loop(void) {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (g_rx_len > 0) {
        g_rx_buf[g_rx_len] = '\0';
        handleCommand(g_rx_buf);
        g_rx_len = 0;
      }
    } else if (g_rx_len < sizeof(g_rx_buf) - 1) {
      g_rx_buf[g_rx_len++] = c;
    }
  }
}
