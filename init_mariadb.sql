-- HealthChat MariaDB Schema (Encrypted Envelope Storage)
-- Run init_mariadb_admin.sql first to set up database and user privileges.

USE healthchat;

-- 1. Users & Authentication Table
CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    kdf_salt VARBINARY(32) NOT NULL,
    wrapped_dek VARBINARY(256) NOT NULL,
    dek_nonce VARBINARY(32) NOT NULL,
    recovery_wrapped_dek VARBINARY(256),
    recovery_salt VARBINARY(32),
    recovery_nonce VARBINARY(32),
    encrypted_profile LONGBLOB,
    profile_nonce VARBINARY(32),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    INDEX idx_sessions_expires (expires_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Encrypted Health Data Tables (Composite PK user_id + date / activity_id)
CREATE TABLE IF NOT EXISTS daily_summary (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sleep_data (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS body_battery (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stress_data (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hrv_data (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS activities (
    user_id BIGINT NOT NULL,
    activity_id BIGINT NOT NULL,
    date VARCHAR(20),
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, activity_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_activities_user_date (user_id, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS body_composition (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS calorie_burn (
    user_id BIGINT NOT NULL,
    date VARCHAR(20) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. External Data Sources (Strava, Garmin Connect, Withings, Fitbit)
-- Credentials and OAuth tokens are encrypted with the user's own DEK (S-13).
CREATE TABLE IF NOT EXISTS user_datasources (
    user_id BIGINT NOT NULL,
    provider VARCHAR(32) NOT NULL,
    encrypted_payload LONGBLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    connected TINYINT(1) NOT NULL DEFAULT 0,
    last_sync_at DATETIME NULL,
    last_sync_count INT NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, provider),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sync_metadata (
    user_id BIGINT NOT NULL,
    `key` VARCHAR(100) NOT NULL,
    `value` TEXT,
    PRIMARY KEY (user_id, `key`),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
