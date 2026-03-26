import os
from typing import Optional
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def init_pool():
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=os.environ["DATABASE_URL"],
    )


def get_conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool.getconn()


def release_conn(conn):
    if _pool is not None:
        _pool.putconn(conn)


class PooledConn:
    """コンテキストマネージャで接続を自動返却する"""
    def __enter__(self):
        self.conn = get_conn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            release_conn(self.conn)
        return False


def init_db():
    with PooledConn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id         SERIAL PRIMARY KEY,
                    title      TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    id         SERIAL PRIMARY KEY,
                    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    parent_id  INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
                    persona    TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)


def create_topic(title: str) -> int:
    with PooledConn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO topics (title) VALUES (%s) RETURNING id", (title,))
            return cur.fetchone()[0]


def get_topics() -> list:
    with PooledConn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM topics ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]


def get_topic(topic_id: int) -> Optional[dict]:
    with PooledConn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM topics WHERE id = %s", (topic_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_node(node_id: int) -> Optional[dict]:
    with PooledConn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM nodes WHERE id = %s", (node_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def create_node(topic_id: int, parent_id: Optional[int], persona: str, content: str) -> int:
    with PooledConn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nodes (topic_id, parent_id, persona, content) VALUES (%s, %s, %s, %s) RETURNING id",
                (topic_id, parent_id, persona, content),
            )
            return cur.fetchone()[0]


def create_ai_nodes(topic_id: int, parent_id: int, responses: dict) -> None:
    """AIペルソナのノードを単一トランザクションで一括保存する"""
    with PooledConn() as conn:
        with conn.cursor() as cur:
            for persona, content in responses.items():
                cur.execute(
                    "INSERT INTO nodes (topic_id, parent_id, persona, content) VALUES (%s, %s, %s, %s)",
                    (topic_id, parent_id, persona, content),
                )


def get_nodes(topic_id: int) -> list:
    with PooledConn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM nodes WHERE topic_id = %s ORDER BY created_at ASC",
                (topic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_ancestor_chain(node_id: int) -> list:
    """ルートから node_id までの祖先ノードチェーンを返す（ルート→末端の順）"""
    with PooledConn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH RECURSIVE ancestors AS (
                    SELECT * FROM nodes WHERE id = %s
                    UNION ALL
                    SELECT n.* FROM nodes n
                    INNER JOIN ancestors a ON n.id = a.parent_id
                )
                SELECT * FROM ancestors ORDER BY id ASC
            """, (node_id,))
            return [dict(r) for r in cur.fetchall()]
