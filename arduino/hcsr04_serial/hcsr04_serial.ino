/*
 * HC-SR04 → JSON sur port série
 * Branché sur Arduino Uno, connecté via USB à la Raspberry Pi
 *
 * Câblage :
 *   HC-SR04 VCC  → 5V
 *   HC-SR04 GND  → GND
 *   HC-SR04 TRIG → Pin 9
 *   HC-SR04 ECHO → Pin 10
 *
 * Sortie série (9600 baud) — une ligne JSON toutes les 200ms :
 *   {"distance_cm":45.3,"obstacle":false}
 *   {"distance_cm":null,"obstacle":false,"error":"timeout"}
 */

#define TRIG_PIN 9
#define ECHO_PIN 10
#define OBSTACLE_THRESHOLD_CM 20.0
#define MEASURE_INTERVAL_MS   200
#define TIMEOUT_US            30000   // 30ms max = ~5m portée max

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
  delay(100);
}

void loop() {
  float distance = measure_cm();

  if (distance < 0) {
    // Timeout ou hors portée
    Serial.println("{\"distance_cm\":null,\"obstacle\":false,\"error\":\"timeout\"}");
  } else {
    bool obstacle = distance < OBSTACLE_THRESHOLD_CM;
    Serial.print("{\"distance_cm\":");
    Serial.print(distance, 1);
    Serial.print(",\"obstacle\":");
    Serial.print(obstacle ? "true" : "false");
    Serial.println("}");
  }

  delay(MEASURE_INTERVAL_MS);
}

/*
 * Envoie une impulsion TRIG et mesure la durée de l'écho ECHO.
 * Retourne la distance en cm, ou -1 si timeout.
 */
float measure_cm() {
  // Impulsion TRIG de 10µs
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Mesure durée ECHO (µs) avec timeout
  long duration = pulseIn(ECHO_PIN, HIGH, TIMEOUT_US);

  if (duration == 0) {
    return -1.0;  // timeout
  }

  // Vitesse du son = 343 m/s → 0.0343 cm/µs ÷ 2 (aller-retour)
  return duration * 0.01715;
}
