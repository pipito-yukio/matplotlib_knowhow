\connnect healthcare_db

DROP INDEX IF EXISTS bodyhealth.idx_person_email;
DROP TABLE IF EXISTS bodyhealth.sleep_management;
DROP TABLE IF EXISTS bodyhealth.blood_pressure;
DROP TABLE IF EXISTS bodyhealth.body_temperature;
DROP TABLE IF EXISTS bodyhealth.walking_count;
DROP TABLE IF EXISTS bodyhealth.nocturia_factors;
DROP TABLE IF EXISTS bodyhealth.person;
DROP SCHEMA IF EXISTS bodyhealth;

-- 体健康
CREATE SCHEMA IF NOT EXISTS bodyhealth;

-- ユーザーテーブル
CREATE TABLE IF NOT EXISTS bodyhealth.person(
   id smallint NOT NULL,
   email varchar(50) NOT NULL,
   name varchar(24) NOT NULL,
   CONSTRAINT pk_person PRIMARY KEY (id)
);
CREATE UNIQUE INDEX idx_person_email ON bodyhealth.person (email);

-- 睡眠管理テーブル
CREATE TABLE IF NOT EXISTS bodyhealth.sleep_management(
  pid smallint NOT NULL,
  measurement_day date NOT NULL,
  wakeup_time time without time zone NOT NULL,
  sleep_score smallint,
  sleeping_time time without time zone NOT NULL,
  deep_sleeping_time time without time zone
);

-- 血圧管理テーブル
CREATE TABLE IF NOT EXISTS bodyhealth.blood_pressure(
  pid smallint NOT NULL,
  measurement_day date NOT NULL,
  morning_measurement_time time without time zone,
  morning_max smallint,
  morning_min smallint,
  morning_pulse_rate smallint,
  evening_measurement_time time without time zone,
  evening_max smallint,
  evening_min smallint,
  evening_pulse_rate smallint
);

-- 体温測定テーブル: 任意
CREATE TABLE IF NOT EXISTS bodyhealth.body_temperature(
  pid smallint NOT NULL,
  measurement_day date NOT NULL,
  measurement_time time without time zone,
  temperature real
);

-- 歩数テーブル
CREATE TABLE IF NOT EXISTS bodyhealth.walking_count(
  pid smallint NOT NULL,
  measurement_day date NOT NULL,
  counts smallint NOT NULL
);

-- 夜中トイレ回数要因テーブル
CREATE TABLE IF NOT EXISTS bodyhealth.nocturia_factors(
  pid smallint NOT NULL,
  measurement_day date NOT NULL,
  midnight_toilet_visits smallint NOT NULL,
  has_coffee boolean,
  has_tea boolean,
  has_alcohol boolean,
  has_nutrition_drink boolean,
  has_sports_drink boolean,
  has_diuretic boolean,
  take_medicine boolean,
  take_bathing boolean,
  condition_memo varchar(255)
);

ALTER TABLE bodyhealth.sleep_management ADD CONSTRAINT pkey_sleep_management
   PRIMARY KEY (pid, measurement_day);
ALTER TABLE bodyhealth.sleep_management ADD CONSTRAINT fkey_sleep_management_person
   FOREIGN KEY (pid) REFERENCES bodyhealth.person(id) ON DELETE CASCADE;

ALTER TABLE bodyhealth.blood_pressure ADD CONSTRAINT pkey_blood_pressure
   PRIMARY KEY (pid, measurement_day);
ALTER TABLE bodyhealth.blood_pressure ADD CONSTRAINT fkey_blood_pressure_person
   FOREIGN KEY (pid) REFERENCES bodyhealth.person(id) ON DELETE CASCADE;

ALTER TABLE bodyhealth.body_temperature ADD CONSTRAINT pkey_body_temperature
   PRIMARY KEY (pid, measurement_day);
ALTER TABLE bodyhealth.body_temperature ADD CONSTRAINT fkey_body_temperature_person
   FOREIGN KEY (pid) REFERENCES bodyhealth.person(id) ON DELETE CASCADE;

ALTER TABLE bodyhealth.walking_count ADD CONSTRAINT pkey_walking_count
   PRIMARY KEY (pid, measurement_day);
ALTER TABLE bodyhealth.walking_count ADD CONSTRAINT fkey_walking_count_person
   FOREIGN KEY (pid) REFERENCES bodyhealth.person(id) ON DELETE CASCADE;

ALTER TABLE bodyhealth.nocturia_factors ADD CONSTRAINT pkey_nocturia_factors
   PRIMARY KEY (pid, measurement_day);
ALTER TABLE bodyhealth.nocturia_factors ADD CONSTRAINT fkey_nocturia_factors_person
   FOREIGN KEY (pid) REFERENCES bodyhealth.person(id) ON DELETE CASCADE;

ALTER SCHEMA bodyhealth OWNER TO developer;
ALTER TABLE bodyhealth.person OWNER TO developer;
ALTER TABLE bodyhealth.sleep_management OWNER TO developer;
ALTER TABLE bodyhealth.blood_pressure OWNER TO developer;
ALTER TABLE bodyhealth.body_temperature OWNER TO developer;
ALTER TABLE bodyhealth.walking_count OWNER TO developer;
ALTER TABLE bodyhealth.nocturia_factors OWNER TO developer;

