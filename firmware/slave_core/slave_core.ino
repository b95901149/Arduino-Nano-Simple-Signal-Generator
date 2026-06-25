/*
 * Arduino Nano Slave Core (ATmega328P)
 * SoftwareSerial on D10 (RX), D11 (TX) @ 9600 baud
 * Controlled by master via cross-wired SoftwareSerial link.
 *
 * Wiring to master:
 *   Slave D10 (RX) <-- Master D11 (TX)
 *   Slave D11 (TX) --> Master D10 (RX)
 *   Master D12 (TRIG OUT) --> Slave D12 (TRIG IN, interrupt)
 *   GND common
 */

#include <Arduino.h>
#include <EEPROM.h>
#include <SoftwareSerial.h>
#include <stdlib.h>
#include <string.h>

static const uint8_t SS_RX_PIN = 10;
static const uint8_t SS_TX_PIN = 11;
static const uint8_t TRIGGER_PIN = 12;
static const uint32_t SS_BAUD = 9600;

static const uint8_t INPUT_PINS[] = {5, 6, 7, 8};
static const uint8_t OUTPUT_PINS[] = {9, 13};
static const uint8_t OUTPUT_PIN_COUNT = 2;

static SoftwareSerial g_ss(SS_RX_PIN, SS_TX_PIN);

static volatile uint8_t g_comm_gate = 0;

static const uint8_t BLINK_LED_PIN = 13;
static const uint32_t BLINK_MIN_MS = 100UL;
static const uint32_t BLINK_MAX_MS = 5000UL;
static const float VAR_E_MIN_SEC = 0.1f;
static const float VAR_E_MAX_SEC = 5.0f;
static const float VAR_E_DEFAULT_SEC = 1.0f;

static uint32_t g_blink_period_ms = 0;
static uint32_t g_blink_last_ms = 0;
static uint8_t g_blink_led_on = 0;

char g_rx_buf[80];
uint8_t g_rx_len = 0;

static char g_ss_line_buf[80];
static uint8_t g_ss_line_len = 0;
static char g_last_ss_line[80];
static uint32_t g_ss_rx_char_count = 0;

static const uint16_t VAR_EEPROM_MAGIC = 0xCAFEU;
static const int VAR_EEPROM_ADDR = 0;

struct VarBlock {
  uint16_t magic;
  float A;
  float B;
  float C;
  float D;
  float E;
};

static VarBlock g_vars;

static void loadVarsFromEeprom(void) {
  EEPROM.get(VAR_EEPROM_ADDR, g_vars);
  if (g_vars.magic != VAR_EEPROM_MAGIC) {
    g_vars.magic = VAR_EEPROM_MAGIC;
    g_vars.A = 0.0f;
    g_vars.B = 0.0f;
    g_vars.C = 0.0f;
    g_vars.D = 0.0f;
    g_vars.E = VAR_E_DEFAULT_SEC;
    EEPROM.put(VAR_EEPROM_ADDR, g_vars);
  }
}

static void saveVarsToEeprom(void) {
  g_vars.magic = VAR_EEPROM_MAGIC;
  EEPROM.put(VAR_EEPROM_ADDR, g_vars);
}

static float *varPtrByName(char name) {
  switch (name) {
    case 'A':
      return &g_vars.A;
    case 'B':
      return &g_vars.B;
    case 'C':
      return &g_vars.C;
    case 'D':
      return &g_vars.D;
    case 'E':
      return &g_vars.E;
    default:
      return NULL;
  }
}

static void sendVarValues(Stream &out) {
  out.print(F("VAR:A="));
  out.print(g_vars.A, 3);
  out.print(F(",B="));
  out.print(g_vars.B, 3);
  out.print(F(",C="));
  out.print(g_vars.C, 3);
  out.print(F(",D="));
  out.print(g_vars.D, 3);
  out.print(F(",E="));
  out.println(g_vars.E, 3);
}

static void sendVarAckUsb(void) {
  Serial.print(F("VARACK:A="));
  Serial.print(g_vars.A, 3);
  Serial.print(F(",B="));
  Serial.print(g_vars.B, 3);
  Serial.print(F(",C="));
  Serial.print(g_vars.C, 3);
  Serial.print(F(",D="));
  Serial.print(g_vars.D, 3);
  Serial.print(F(",E="));
  Serial.println(g_vars.E, 3);
}

static bool parseVarAll(const char *s, float *out5) {
  for (uint8_t i = 0; i < 5; i++) {
    char *end = NULL;
    double val = strtod(s, &end);
    if (end == s) {
      return false;
    }
    out5[i] = (float)val;
    s = end;
    if (i < 4) {
      if (*s != ',') {
        return false;
      }
      s++;
    } else if (*s != '\0') {
      return false;
    }
  }
  return true;
}

static bool applyVarBlock(const float *vals, Stream &out) {
  bool changed = false;
  bool e_changed = false;
  if (g_vars.A != vals[0]) {
    g_vars.A = vals[0];
    changed = true;
  }
  if (g_vars.B != vals[1]) {
    g_vars.B = vals[1];
    changed = true;
  }
  if (g_vars.C != vals[2]) {
    g_vars.C = vals[2];
    changed = true;
  }
  if (g_vars.D != vals[3]) {
    g_vars.D = vals[3];
    changed = true;
  }
  if (g_vars.E != vals[4]) {
    g_vars.E = vals[4];
    changed = true;
    e_changed = true;
  }
  if (changed) {
    saveVarsToEeprom();
    sendVarAckUsb();
  }
  if (e_changed) {
    syncEToBlink();
  }
  out.println(F("OK"));
  return true;
}

static bool handleVarCommand(const char *args, Stream &out) {
  if (strcmp(args, "?") == 0) {
    sendVarValues(out);
    return true;
  }

  if (strncmp(args, "ALL:", 4) == 0) {
    float vals[5];
    if (!parseVarAll(args + 4, vals)) {
      out.println(F("ERR:VAR_FORMAT"));
      return true;
    }
    applyVarBlock(vals, out);
    return true;
  }

  char name = args[0];
  if (name < 'A' || name > 'E') {
    out.println(F("ERR:VAR_NAME"));
    return true;
  }

  const char *sep = args + 1;
  if (*sep != ':' && *sep != '=') {
    out.println(F("ERR:VAR_FORMAT"));
    return true;
  }

  float *slot = varPtrByName(name);
  if (slot == NULL) {
    out.println(F("ERR:VAR_NAME"));
    return true;
  }

  float val = (float)atof(sep + 1);
  if (*slot != val) {
    *slot = val;
    saveVarsToEeprom();
    sendVarAckUsb();
    if (name == 'E') {
      syncEToBlink();
    }
  } else if (name == 'E') {
    syncEToBlink();
  }
  out.println(F("OK"));
  return true;
}

static void echoSsRxChar(char c) {
  Serial.print(F("SSRXC:"));
  if (c >= 32 && c < 127) {
    Serial.print(c);
  } else if (c == '\r') {
    Serial.print(F("\\r"));
  } else if (c == '\n') {
    Serial.print(F("\\n"));
  } else {
    Serial.print(F("0x"));
    if ((uint8_t)c < 16) {
      Serial.print('0');
    }
    Serial.print((uint8_t)c, HEX);
  }
  Serial.println();
}

static void sendSsRxStatus(Stream &out) {
  out.print(F("SSRX:LAST="));
  out.print(g_last_ss_line);
  out.print(F(",CHARS="));
  out.print(g_ss_rx_char_count);
  out.print(F(",AVAIL="));
  out.println(g_ss.available());
}

static void stopBlink(void) {
  g_blink_period_ms = 0;
  g_blink_last_ms = 0;
  g_blink_led_on = 0;
  digitalWrite(BLINK_LED_PIN, LOW);
}

static void startBlink(uint32_t period_ms);

static float clampVarESec(float sec) {
  if (sec < VAR_E_MIN_SEC) {
    return VAR_E_MIN_SEC;
  }
  if (sec > VAR_E_MAX_SEC) {
    return VAR_E_MAX_SEC;
  }
  return sec;
}

static uint32_t varESecToMs(float sec) {
  sec = clampVarESec(sec);
  return (uint32_t)(sec * 1000.0f + 0.5f);
}

static void syncEToBlink(void) {
  if (g_vars.E <= 0.0f) {
    stopBlink();
    return;
  }
  g_vars.E = clampVarESec(g_vars.E);
  startBlink(varESecToMs(g_vars.E));
}

static void syncBlinkMsToE(uint32_t period_ms, bool notify_usb) {
  if (period_ms == 0) {
    return;
  }
  float sec = clampVarESec(period_ms / 1000.0f);
  if (g_vars.E != sec) {
    g_vars.E = sec;
    saveVarsToEeprom();
    if (notify_usb) {
      sendVarAckUsb();
    }
  }
}

static void startBlink(uint32_t period_ms) {
  if (period_ms < BLINK_MIN_MS) {
    period_ms = BLINK_MIN_MS;
  }
  if (period_ms > BLINK_MAX_MS) {
    period_ms = BLINK_MAX_MS;
  }
  g_blink_period_ms = period_ms;
  g_blink_last_ms = millis();
  g_blink_led_on = 0;
  digitalWrite(BLINK_LED_PIN, LOW);
}

static void updateBlink(void) {
  if (g_blink_period_ms == 0) {
    return;
  }

  uint32_t half = g_blink_period_ms / 2;
  if (half < 1) {
    half = 1;
  }

  uint32_t now = millis();
  if (now - g_blink_last_ms < half) {
    return;
  }

  g_blink_last_ms = now;
  g_blink_led_on = g_blink_led_on ? 0 : 1;
  digitalWrite(BLINK_LED_PIN, g_blink_led_on ? HIGH : LOW);
}

static void triggerIsr(void) {
  g_comm_gate = digitalRead(TRIGGER_PIN) == HIGH ? 1 : 0;
}

static bool commGateOpen(void) {
  return digitalRead(TRIGGER_PIN) == HIGH;
}

static void syncCommGate(void) {
  g_comm_gate = commGateOpen() ? 1 : 0;
}

static void triggerInit(void) {
  pinMode(TRIGGER_PIN, INPUT);
  uint8_t irq = digitalPinToInterrupt(TRIGGER_PIN);
  if (irq != NOT_AN_INTERRUPT) {
    attachInterrupt(irq, triggerIsr, CHANGE);
  }
  syncCommGate();
}

static void discardSsStream(void) {
  while (g_ss.available() > 0) {
    (void)g_ss.read();
  }
  g_ss_line_len = 0;
}

static void gpioInit(void) {
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(INPUT_PINS[i], INPUT);
  }
  for (uint8_t i = 0; i < OUTPUT_PIN_COUNT; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  triggerInit();
}

static void sendInputs(Stream &out) {
  out.print(F("IN:D5="));
  out.print(digitalRead(5));
  out.print(F(",D6="));
  out.print(digitalRead(6));
  out.print(F(",D7="));
  out.print(digitalRead(7));
  out.print(F(",D8="));
  out.println(digitalRead(8));
}

static void sendOutputs(Stream &out) {
  for (uint8_t i = 0; i < OUTPUT_PIN_COUNT; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    out.print(F("D"));
    out.print(pin);
    out.print(F("="));
    out.print(digitalRead(pin));
    if (i + 1 < OUTPUT_PIN_COUNT) {
      out.print(F(","));
    }
  }
  out.println();
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
  for (uint8_t i = 0; i < OUTPUT_PIN_COUNT; i++) {
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
  if (pin == BLINK_LED_PIN) {
    stopBlink();
  }
  digitalWrite(pin, level ? HIGH : LOW);
  return true;
}

static void handleCommand(char *line, Stream &out) {
  if (strcmp(line, "PING") == 0) {
    out.println(F("PONG"));
    return;
  }

  if (strcmp(line, "SSRX?") == 0) {
    sendSsRxStatus(out);
    return;
  }

  if (strcmp(line, "STATUS?") == 0) {
    out.print(F("SLAVE:OK,GATE="));
    out.print(g_comm_gate);
    out.print(F(",BLINK="));
    out.print(g_blink_period_ms);
    out.print(F(",VAR:A="));
    out.print(g_vars.A, 3);
    out.println();
    return;
  }

  if (strncmp(line, "VAR:", 4) == 0) {
    handleVarCommand(line + 4, out);
    return;
  }

  if (strcmp(line, "VAR?") == 0) {
    sendVarValues(out);
    return;
  }

  if (strncmp(line, "BLINK:", 6) == 0) {
    if (strcmp(line + 6, "STOP") == 0 || strcmp(line + 6, "0") == 0) {
      stopBlink();
      out.println(F("OK"));
      return;
    }

    uint32_t period_ms;
    if (!parseUint(line + 6, &period_ms)) {
      out.println(F("ERR:BLINK_RANGE"));
      return;
    }

    if (period_ms == 0) {
      stopBlink();
      out.println(F("OK"));
      return;
    }

    if (period_ms < BLINK_MIN_MS || period_ms > BLINK_MAX_MS) {
      out.println(F("ERR:BLINK_RANGE"));
      return;
    }

    startBlink(period_ms);
    syncBlinkMsToE(period_ms, true);
    out.println(F("OK"));
    return;
  }

  if (strcmp(line, "IN?") == 0) {
    sendInputs(out);
    return;
  }

  if (strcmp(line, "OUT?") == 0) {
    out.print(F("OUT:"));
    sendOutputs(out);
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
      out.println(F("ERR:OUT_FORMAT"));
      return;
    }

    char pin_buf[8];
    uint8_t pin_len = (uint8_t)(sep - args);
    if (pin_len >= sizeof(pin_buf)) {
      out.println(F("ERR:OUT_PIN"));
      return;
    }
    memcpy(pin_buf, args, pin_len);
    pin_buf[pin_len] = '\0';

    if (!parseUint(pin_buf, &pin) || !parseUint(sep + 1, &level) || level > 1UL) {
      out.println(F("ERR:OUT_FORMAT"));
      return;
    }

    if (!setUserOutput((uint8_t)pin, (uint8_t)level)) {
      out.println(F("ERR:OUT_PIN"));
      return;
    }

    out.println(F("OK"));
    return;
  }

  out.println(F("ERR:UNKNOWN"));
}

static void readUsbStream(void) {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (g_rx_len > 0) {
        g_rx_buf[g_rx_len] = '\0';
        handleCommand(g_rx_buf, Serial);
        g_rx_len = 0;
      }
    } else if (g_rx_len < sizeof(g_rx_buf) - 1) {
      g_rx_buf[g_rx_len++] = c;
    }
  }
}

static void readSsStream(void) {
  if (!commGateOpen()) {
    discardSsStream();
    return;
  }

  while (g_ss.available() > 0) {
    if (!commGateOpen()) {
      discardSsStream();
      return;
    }
    char c = (char)g_ss.read();
    g_ss_rx_char_count++;

    if (c == '\n' || c == '\r') {
      if (g_ss_line_len > 0) {
        g_ss_line_buf[g_ss_line_len] = '\0';
        strncpy(g_last_ss_line, g_ss_line_buf, sizeof(g_last_ss_line) - 1);
        g_last_ss_line[sizeof(g_last_ss_line) - 1] = '\0';
        g_ss_line_len = 0;
        handleCommand(g_ss_line_buf, g_ss);
        g_ss.flush();
      }
    } else if (g_ss_line_len < sizeof(g_ss_line_buf) - 1) {
      g_ss_line_buf[g_ss_line_len++] = c;
    }
  }
}

void setup(void) {
  gpioInit();
  loadVarsFromEeprom();
  g_ss.begin(SS_BAUD);
  Serial.begin(115200);
  syncEToBlink();
  g_ss.println(F("READY SLAVE"));
}

void loop(void) {
  syncCommGate();
  if (commGateOpen()) {
    for (uint8_t pass = 0; pass < 16 && commGateOpen(); pass++) {
      readSsStream();
      if (!g_ss.available()) {
        break;
      }
    }
  } else {
    discardSsStream();
  }
  readUsbStream();
  updateBlink();
}
