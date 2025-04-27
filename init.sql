CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    name TEXT,
    age INTEGER,
    city TEXT,
    gender TEXT,
    description TEXT,
    preference TEXT,
    photo_id TEXT,
    username text
);

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender_filter TEXT;


CREATE TABLE IF NOT EXISTS likes (
    id SERIAL PRIMARY KEY,
    from_user_id BIGINT NOT NULL REFERENCES profiles(user_id),
    to_user_id BIGINT NOT NULL REFERENCES profiles(user_id),
    is_like BOOLEAN NOT NULL,
    UNIQUE (from_user_id, to_user_id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_likes_to_user_id ON likes (to_user_id);

