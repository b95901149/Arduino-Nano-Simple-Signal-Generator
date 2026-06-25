/*
 * Arduino Nano Slave Core (ATmega328P)
 * SoftwareSerial on D10 (RX), D11 (TX) @ 9600 baud
 * Controlled by master via cross-wired SoftwareSerial link.
 *
 * Wiring to master:
 *   Slave D10 (RX) <-- Master D11 (TX)
 *   Slave D11 (TX) --> Master D10 (RX)
 *   GND common
 */

#include <Arduino.h>
#include <SoftwareSerial.h>

static const uint8_t SS_RX_PIN = 10;
static const uint8_t SS_TX_PIN = 11;
static const uint32_t SS_BAUD = 9600;

static const uint8_t INPUT_PINS[] = {5, 6, 7, 8};
static const uint8_t OUTPUT_PINS[] = {9, 12, 13};

static SoftwareSerial g_ss(SS_RX_PIN, SS_TX_PIN);

static const uint8_t BLINK_LED_PIN = 13;
static const uint32_t BLINK_MIN_MS = 100UL;
static const uint32_t BLINK_MAX_MS = 5000UL;

static uint32_t g_blink_period_ms = 0;
static uint32_t g_blink_last_ms = 0;
static uint8_t g_blink_led_on = 0;

char g_rx_buf[80];
uint8_t g_rx_len = 0;

static char g_ss_line_buf[80];
static uint8_t g_ss_line_len = 0;
static char g_last_ss_line[80];
static uint32_t g_ss_rx_char_count = 0;

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

static void gpioInit(void) {
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(INPUT_PINS[i], INPUT);
  }
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
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
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = OUTPUT_PINS[i];
    out.print(F("D"));
    out.print(pin);
    out.print(F("="));
    out.print(digitalRead(pin));
    if (i < 2) {
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
    out.print(F("SLAVE:OK,BLINK="));
    out.println(g_blink_period_ms);
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
  while (g_ss.available() > 0) {
    char c = (char)g_ss.read();
    g_ss_rx_char_count++;
    echoSsRxChar(c);

    if (c == '\n' || c == '\r') {
      if (g_ss_line_len > 0) {
        g_ss_line_buf[g_ss_line_len] = '\0';
        strncpy(g_last_ss_line, g_ss_line_buf, sizeof(g_last_ss_line) - 1);
        g_last_ss_line[sizeof(g_last_ss_line) - 1] = '\0';
        g_ss_line_len = 0;
        Serial.print(F("SSRX:"));
        Serial.println(g_last_ss_line);
        handleCommand(g_ss_line_buf, g_ss);
      }
    } else if (g_ss_line_len < sizeof(g_ss_line_buf) - 1) {
      g_ss_line_buf[g_ss_line_len++] = c;
    }
  }
}

void setup(void) {
  gpioInit();
  g_ss.begin(SS_BAUD);
  Serial.begin(115200);
  g_ss.println(F("READY SLAVE"));
}

void loop(void) {
  readSsStream();
  readUsbStream();
  updateBlink();
}
