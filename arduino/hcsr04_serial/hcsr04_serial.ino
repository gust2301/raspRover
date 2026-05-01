/*
 * 2x HC-SR04 (avant + arrière) → JSON sur port série
 * Arduino Uno connecté via USB à la Raspberry Pi
 *
 * Câblage :
 *   Capteur AVANT  : TRIG → pin 9  / ECHO → pin 10
 *   Capteur ARRIÈRE: TRIG → pin 7  / ECHO → pin 8
 *   VCC → 5V  /  GND → GND  (les deux capteurs)
 *
 * Sortie série (9600 baud) — une ligne JSON toutes les 200ms :
 *   {"front_cm":45.3,"front_ok":true,"rear_cm":120.0,"rear_ok":true,
 *    "obstacle_front":false,"obstacle_rear":false}
 *
 *   Si timeout : front_cm / rear_cm = null, front_ok / rear_ok = false
 */

// --- Pins ---
#define TRIG_FRONT  9
#define ECHO_FRONT  10
#define TRIG_REAR   7
#define ECHO_REAR   8

// --- Config ---
#define OBSTACLE_CM       20.0   // seuil obstacle en cm
#define MEASURE_INTERVAL  200    // ms entre deux envois
#define TIMEOUT_US        30000  // 30ms ≈ 5m portée max

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_FRONT, OUTPUT);
  pinMode(ECHO_FRONT, INPUT);
  pinMode(TRIG_REAR,  OUTPUT);
  pinMode(ECHO_REAR,  INPUT);
  digitalWrite(TRIG_FRONT, LOW);
  digitalWrite(TRIG_REAR,  LOW);
  delay(100);
}

void loop() {
  float front = measure_cm(TRIG_FRONT, ECHO_FRONT);
  delay(30);  // délai entre les deux mesures pour éviter les interférences
  float rear  = measure_cm(TRIG_REAR,  ECHO_REAR);

  bool front_ok = (front >= 0);
  bool rear_ok  = (rear  >= 0);
  bool obs_front = front_ok && (front < OBSTACLE_CM);
  bool obs_rear  = rear_ok  && (rear  < OBSTACLE_CM);

  // Sérialisation JSON manuelle (pas de lib JSON sur Uno)
  Serial.print("{");
  Serial.print("\"front_cm\":");
  if (front_ok) Serial.print(front, 1); else Serial.print("null");
  Serial.print(",\"front_ok\":");
  Serial.print(front_ok ? "true" : "false");
  Serial.print(",\"rear_cm\":");
  if (rear_ok) Serial.print(rear, 1); else Serial.print("null");
  Serial.print(",\"rear_ok\":");
  Serial.print(rear_ok ? "true" : "false");
  Serial.print(",\"obstacle_front\":");
  Serial.print(obs_front ? "true" : "false");
  Serial.print(",\"obstacle_rear\":");
  Serial.print(obs_rear ? "true" : "false");
  Serial.println("}");

  delay(MEASURE_INTERVAL);
}

/*
 * Envoie une impulsion TRIG et mesure la durée ECHO.
 * Retourne la distance en cm, ou -1 si timeout.
 */
float measure_cm(int trig, int echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);

  long duration = pulseIn(echo, HIGH, TIMEOUT_US);
  if (duration == 0) return -1.0;

  return duration * 0.01715;  // cm = µs × (0.0343 / 2)
}
