"""sections_checked в verifications

Revision ID: 4a19f2c7e8b1
Revises: 0c875f68a577
Create Date: 2026-10-08 15:20:00.000000

Зачем поле: проверка проекта отдаёт два разных числа — сколько разделов
охвачено и сколько утверждений без источника. Раньше хранилось только
второе, поэтому по сохранённому результату нельзя было сказать, была ли
проверка полной. Интерфейсу это нужно, чтобы показать охват честно.

Значение по умолчанию 0, а не NULL: проверка всегда что-то охватывает,
а «неизвестно» и «ноль» для пользователя — разные утверждения.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a19f2c7e8b1"
down_revision: str | None = "0c875f68a577"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default обязателен: в таблице уже есть строки, а nullable=False
    # без значения по умолчанию обрушил бы миграцию на реальных данных.
    with op.batch_alter_table("verifications", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "sections_checked",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("verifications", schema=None) as batch_op:
        batch_op.drop_column("sections_checked")