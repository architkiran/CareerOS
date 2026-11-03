"""Candidate profile, facts, skills, experience, projects, role lanes, work authorization.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03 01:28:22.205882
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profile",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("current_location", sa.String(length=200), nullable=True),
        sa.Column("relocation_preferences_json", sa.JSON(), nullable=False),
        sa.Column("graduation_date", sa.Date(), nullable=True),
        sa.Column("availability_date", sa.Date(), nullable=True),
        sa.Column("salary_floor", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profile")),
    )
    op.create_table(
        "role_lane",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("scoring_weights_json", sa.JSON(), nullable=False),
        sa.Column("resume_template_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_lane")),
        sa.UniqueConstraint("name", name=op.f("uq_role_lane_name")),
    )
    op.create_table(
        "skill",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.String(length=100), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill")),
        sa.UniqueConstraint("canonical_name", name=op.f("uq_skill_canonical_name")),
    )
    op.create_table(
        "candidate_skill",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("skill_id", sa.String(length=32), nullable=False),
        sa.Column("proficiency", sa.String(length=30), nullable=True),
        sa.Column("evidence_fact_ids_json", sa.JSON(), nullable=False),
        sa.Column("last_used_year", sa.Integer(), nullable=True),
        sa.Column("verified_status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_candidate_skill_profile_id_candidate_profile"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skill.id"],
            name=op.f("fk_candidate_skill_skill_id_skill"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "skill_id", name=op.f("pk_candidate_skill")),
    )
    op.create_table(
        "experience",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("organization", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("verified_status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_experience_profile_id_candidate_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experience")),
    )
    with op.batch_alter_table("experience", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_experience_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "profile_fact",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("fact_key", sa.String(length=100), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("verified_status", sa.String(length=20), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_profile_fact_profile_id_candidate_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_fact")),
    )
    with op.batch_alter_table("profile_fact", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_profile_fact_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "project",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("technologies_json", sa.JSON(), nullable=False),
        sa.Column("outcomes_json", sa.JSON(), nullable=False),
        sa.Column("evidence_notes", sa.Text(), nullable=True),
        sa.Column("verified_status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_project_profile_id_candidate_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_project_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "work_authorization_profile",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("status_text", sa.String(length=200), nullable=True),
        sa.Column("requires_sponsorship_now", sa.String(length=10), nullable=False),
        sa.Column("requires_sponsorship_future", sa.String(length=10), nullable=False),
        sa.Column("authorized_until", sa.Date(), nullable=True),
        sa.Column("constraints", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_work_authorization_profile_profile_id_candidate_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_authorization_profile")),
        sa.UniqueConstraint("profile_id", name=op.f("uq_work_authorization_profile_profile_id")),
    )


def downgrade() -> None:
    op.drop_table("work_authorization_profile")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_project_profile_id"))

    op.drop_table("project")
    with op.batch_alter_table("profile_fact", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_profile_fact_profile_id"))

    op.drop_table("profile_fact")
    with op.batch_alter_table("experience", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_experience_profile_id"))

    op.drop_table("experience")
    op.drop_table("candidate_skill")
    op.drop_table("skill")
    op.drop_table("role_lane")
    op.drop_table("candidate_profile")
