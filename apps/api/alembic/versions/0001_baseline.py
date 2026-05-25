"""baseline — capture current ORM schema as the first Alembic revision.

This is the **baseline migration**: it captures the full schema that the
project has accumulated up to (but not including) the pgvector native KNN
work. It exists so the project can move from
``Base.metadata.create_all()`` to a proper migration-driven workflow
without rebuilding existing databases.

For operators with **existing databases** (previously bootstrapped via
``Base.metadata.create_all()`` from ``app/main.py`` or ``app/db/seed.py``):

    cd apps/api
    alembic stamp 0001_baseline   # mark this revision as already applied
    alembic upgrade head          # apply the pgvector migration on top

For **fresh databases** just run ``alembic upgrade head`` — this baseline
will create every table and then later revisions stack on top.

The body below is the verbatim ``alembic revision --autogenerate`` output
against the SQLAlchemy metadata: ``documents``, ``users``, ``trends``,
``recipes``, ``ingredients``, ``recipe_ingredients``, ``subscriptions``,
``notifications``, ``user_favorite_keywords`` and the
``vector_search_datapoints`` table that the next revision augments with
pgvector's ``vector(N)`` column + ANN index.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("institution", sa.String(length=60), nullable=False),
        sa.Column("region", sa.String(length=60), nullable=False),
        sa.Column("period", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("modern_text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("license", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ingredients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("default_unit", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingredients_name"), "ingredients", ["name"], unique=True)
    op.create_table(
        "trends",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=60), nullable=False),
        sa.Column("change_percent", sa.Float(), nullable=False),
        sa.Column("is_up", sa.Boolean(), nullable=False),
        sa.Column("week_of", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trends_keyword"), "trends", ["keyword"], unique=False)
    op.create_index(op.f("ix_trends_region"), "trends", ["region"], unique=False)
    op.create_index(op.f("ix_trends_week_of"), "trends", ["week_of"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.Enum("USER", "ADMIN", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False),
        sa.Column("persona", sa.String(length=60), nullable=False),
        sa.Column("preferred_regions", sa.JSON(), nullable=False),
        sa.Column("preferred_keywords", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "vector_search_datapoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("datapoint_id", sa.String(length=255), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("restricts", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", "datapoint_id", name="uq_vsd_namespace_datapoint"),
    )
    op.create_index(
        "ix_vsd_namespace", "vector_search_datapoints", ["namespace"], unique=False
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "type", sa.Enum("FAVORITE_KEYWORD_TRENDING", name="notificationtype"), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "recipes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_document_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=60), nullable=False),
        sa.Column("era", sa.String(length=60), nullable=False),
        sa.Column("diet", sa.String(length=60), nullable=False),
        sa.Column("menu_type", sa.String(length=60), nullable=False),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("time_minutes", sa.Integer(), nullable=False),
        sa.Column("servings", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_krw", sa.Integer(), nullable=False),
        sa.Column("estimated_price_krw", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("sns_caption", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("source_attribution", sa.Text(), nullable=False),
        sa.Column("is_recommended", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PENDING_REVIEW",
                "APPROVED",
                "REJECTED",
                "FLAGGED",
                name="recipestatus",
            ),
            nullable=False,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("is_selling", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipes_keyword"), "recipes", ["keyword"], unique=False)
    op.create_index(op.f("ix_recipes_status"), "recipes", ["status"], unique=False)
    op.create_index(op.f("ix_recipes_user_id"), "recipes", ["user_id"], unique=False)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan", sa.Enum("FREE", "PRO", "B2B", name="plan"), nullable=False),
        sa.Column("monthly_recipe_count", sa.Integer(), nullable=False),
        sa.Column("billing_key", sa.String(length=255), nullable=False),
        sa.Column("toss_customer_key", sa.String(length=100), nullable=False),
        sa.Column("next_billing_date", sa.Date(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_payment_status", sa.String(length=20), nullable=False),
        sa.Column("last_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=True
    )
    op.create_table(
        "user_favorite_keywords",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "keyword", name="uq_user_favorite_keyword"),
    )
    op.create_index(
        op.f("ix_user_favorite_keywords_keyword"),
        "user_favorite_keywords",
        ["keyword"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_favorite_keywords_user_id"),
        "user_favorite_keywords",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("recipe_id", sa.String(length=36), nullable=False),
        sa.Column("ingredient_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.String(length=60), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("recipe_id", "ingredient_id"),
    )


def downgrade() -> None:
    op.drop_table("recipe_ingredients")
    op.drop_index(
        op.f("ix_user_favorite_keywords_user_id"), table_name="user_favorite_keywords"
    )
    op.drop_index(
        op.f("ix_user_favorite_keywords_keyword"), table_name="user_favorite_keywords"
    )
    op.drop_table("user_favorite_keywords")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_recipes_user_id"), table_name="recipes")
    op.drop_index(op.f("ix_recipes_status"), table_name="recipes")
    op.drop_index(op.f("ix_recipes_keyword"), table_name="recipes")
    op.drop_table("recipes")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_vsd_namespace", table_name="vector_search_datapoints")
    op.drop_table("vector_search_datapoints")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_trends_week_of"), table_name="trends")
    op.drop_index(op.f("ix_trends_region"), table_name="trends")
    op.drop_index(op.f("ix_trends_keyword"), table_name="trends")
    op.drop_table("trends")
    op.drop_index(op.f("ix_ingredients_name"), table_name="ingredients")
    op.drop_table("ingredients")
    op.drop_table("documents")
