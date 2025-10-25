from sqlalchemy import text
from .base import engine

DDL = """
ALTER TABLE ticket_messages
  ADD COLUMN IF NOT EXISTS message_text text,
  ADD COLUMN IF NOT EXISTS caption text;

CREATE TABLE IF NOT EXISTS message_attachments (
  id serial primary key,
  ticket_message_id int not null references ticket_messages(id) on delete cascade,
  media_type varchar(32) not null,
  file_id varchar(256) not null,
  file_unique_id varchar(128),
  file_name varchar(256),
  mime_type varchar(64),
  width int,
  height int,
  duration int,
  local_path varchar(512),
  created_at timestamp default now()
);

CREATE INDEX IF NOT EXISTS ix_msg_att_msg ON message_attachments(ticket_message_id);
"""

def bootstrap_indexes_and_tables() -> None:
    with engine.begin() as conn:
        for stmt in filter(None, (s.strip() for s in DDL.split(";"))):
            conn.exec_driver_sql(stmt)
