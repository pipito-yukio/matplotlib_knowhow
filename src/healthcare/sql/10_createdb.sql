CREATE ROLE developer WITH LOGIN PASSWORD 'developer-passwd';
CREATE DATABASE healthcare_db WITH OWNER=developer ENCODING='UTF-8' LC_COLLATE='ja_JP.UTF-8' LC_CTYPE='ja_JP.UTF-8' TEMPLATE=template0;
GRANT ALL PRIVILEGES ON DATABASE healthcare_db TO developer;
