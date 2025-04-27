-- Create the profiles table if it doesn't exist
CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY, -- Auto-incrementing primary key for the table row
    user_id BIGINT NOT NULL UNIQUE, -- Telegram user ID, must be unique
    name TEXT,
    age INTEGER,
    city TEXT,
    gender TEXT,
    description TEXT,
    preference TEXT,
    photo_id TEXT,
    username text
);

-- Add gender and gender_filter columns if they don't exist (idempotent)
-- Note: These ALTER TABLE statements might be redundant if the CREATE TABLE
-- already includes these columns as shown above, but they are harmless
-- if you ran them separately before. Keeping them for robustness.
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS gender_filter TEXT;


-- Create the likes table if it doesn't exist
CREATE TABLE IF NOT EXISTS likes (
    id SERIAL PRIMARY KEY, -- Auto-incrementing primary key for the table row
    from_user_id BIGINT NOT NULL REFERENCES profiles(user_id), -- Foreign key to profiles table
    to_user_id BIGINT NOT NULL REFERENCES profiles(user_id),   -- Foreign key to profiles table
    is_like BOOLEAN NOT NULL, -- TRUE for like, FALSE for dislike
    -- Ensure that a user can only like/dislike another user once
    UNIQUE (from_user_id, to_user_id),
    -- Optional: Add a timestamp for when the like/dislike occurred
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Optional: Add an index to speed up lookups on to_user_id in the likes table
-- This can be helpful for finding who liked a specific user.
CREATE INDEX IF NOT EXISTS idx_likes_to_user_id ON likes (to_user_id);

