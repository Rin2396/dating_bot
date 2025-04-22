CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name TEXT,
    age INTEGER,
    city TEXT,
    gender TEXT,
    description TEXT,
    preference TEXT,
    photo_id TEXT
);


CREATE TABLE IF NOT EXISTS likes (
    id SERIAL PRIMARY KEY,
    from_user_id BIGINT NOT NULL,
    to_user_id BIGINT NOT NULL,
    is_like BOOLEAN NOT NULL,
    UNIQUE (from_user_id, to_user_id)
);
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender_filter TEXT;
