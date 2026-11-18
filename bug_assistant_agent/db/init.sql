-- Schema for the bug tracker. Runs once, when the container first starts.

-- pg_trgm gives fuzzy text matching (similarity()). We use it later for search and duplicate detection,
-- without needing paid embeddings.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tickets (
    ticket_id     SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    assignee      TEXT,                                   -- NULL = nobody picked it up yet
    priority      TEXT NOT NULL DEFAULT 'P2'
                  CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),   -- P0 = drop everything, P3 = nice to have
    status        TEXT NOT NULL DEFAULT 'Open'
                  CHECK (status IN ('Open', 'In Progress', 'Closed')),
    -- set when a ticket is closed as a duplicate; points at the original ticket
    duplicate_of  INTEGER REFERENCES tickets(ticket_id)
                  CHECK (duplicate_of <> ticket_id),      -- a ticket can't duplicate itself
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigram index so fuzzy title search stays fast as the table grows.
CREATE INDEX tickets_title_trgm ON tickets USING gin (title gin_trgm_ops);

-- Sample tickets about a made-up web app. Some are near-duplicates on purpose (#1/#9, #3/#10)
-- so the duplicate-detection feature has something to catch.
INSERT INTO tickets (title, description, assignee, priority, status, created_at) VALUES
('Login page crashes on Safari',
 'Clicking "Sign in" on Safari 18 shows a blank white page. Console: TypeError: undefined is not an object (evaluating ''window.crypto.randomUUID'').',
 'maria.lopez', 'P1', 'Open', now() - interval '6 days'),
('Password reset email never arrives',
 'Users report the reset email does not arrive. SMTP logs show 421 rate-limit errors from the mail provider.',
 'dev.patel', 'P1', 'In Progress', now() - interval '5 days'),
('Dashboard loads very slowly',
 'The /dashboard page takes 8-10 seconds to load for accounts with more than 500 projects. The projects query has no LIMIT.',
 NULL, 'P2', 'Open', now() - interval '5 days'),
('Dark mode toggle does not persist',
 'Dark mode resets to light after a page refresh. The setting is saved in component state only, not in localStorage.',
 'sam.kim', 'P3', 'Closed', now() - interval '4 days'),
('CSV export cuts off at 1000 rows',
 'Exporting the reports table to CSV only includes the first 1000 rows. The export endpoint reuses the paginated query.',
 NULL, 'P2', 'Open', now() - interval '4 days'),
('API returns 500 when project name has emoji',
 'POST /api/projects with a name like "Launch 🚀" returns HTTP 500. DB column is VARCHAR with latin1 collation.',
 'dev.patel', 'P1', 'Open', now() - interval '3 days'),
('Upload fails for files over 10 MB',
 'Uploading attachments larger than 10 MB fails with HTTP 413. The nginx client_max_body_size is still the default.',
 'maria.lopez', 'P2', 'In Progress', now() - interval '3 days'),
('Session expires too quickly',
 'Users get logged out after 5 minutes of inactivity. Expected 30 minutes. SESSION_TTL env var looks misread as seconds.',
 NULL, 'P2', 'Open', now() - interval '2 days'),
('Safari login shows blank screen',
 'On Safari (macOS and iOS) the login button leads to an empty page. Chrome and Firefox are fine.',
 NULL, 'P1', 'Open', now() - interval '1 day'),
('Dashboard is slow for big accounts',
 'Large customers say the dashboard takes forever to open. Maybe related to the number of projects.',
 NULL, 'P2', 'Open', now() - interval '1 day'),
('Typo on pricing page',
 'The pricing page says "Profesional plan" instead of "Professional plan".',
 'sam.kim', 'P3', 'Open', now() - interval '12 hours');

-- Keep updated_at equal to created_at for the seed rows (new rows get now()).
UPDATE tickets SET updated_at = created_at;
