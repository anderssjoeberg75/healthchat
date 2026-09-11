-- HealthChat MariaDB Administrative Setup
-- Run once as MariaDB administrator (root) to configure database & user access.
-- NOTE: Root account is preserved per user configuration requirements.

CREATE DATABASE IF NOT EXISTS healthchat CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Application User Privilege Setup
CREATE USER IF NOT EXISTS 'healthchat'@'192.168.101.%' IDENTIFIED BY 'CHANGE_THIS_SECURE_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON healthchat.* TO 'healthchat'@'192.168.101.%';

CREATE USER IF NOT EXISTS 'healthchat'@'localhost' IDENTIFIED BY 'CHANGE_THIS_SECURE_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON healthchat.* TO 'healthchat'@'localhost';

FLUSH PRIVILEGES;
