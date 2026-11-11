-- Install the privileged extension before Silo runs migrations as its own role.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
