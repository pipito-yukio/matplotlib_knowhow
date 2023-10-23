SELECT 
  did, datetime(measurement_time, 'unixepoch', 'localtime'), temp_out, temp_in, humid, pressure
FROM
  t_weather
WHERE
  did=(SELECT id FROM t_device WHERE name='esp8266_1')
  AND
  measurement_time in((SELECT MIN(measurement_time) FROM t_weather), (SELECT MAX(measurement_time) FROM t_weather));

