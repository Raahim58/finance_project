SELECT 'CREATE DATABASE psx_ai_dev OWNER psx'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'psx_ai_dev')\gexec
