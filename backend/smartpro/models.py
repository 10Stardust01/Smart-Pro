"""Read mappings only; ordered SQL migrations remain the schema authority."""
from django.db import models


class Project(models.Model):
    id = models.UUIDField(primary_key=True)
    department_id = models.UUIDField()
    cycle_id = models.UUIDField()
    team_id = models.UUIDField()
    project_type = models.TextField()
    policy_version_id = models.UUIDField()
    project_code = models.TextField()
    title = models.TextField()
    row_version = models.IntegerField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'projects'


class SubmissionItem(models.Model):
    pk = models.CompositePrimaryKey('attempt_id', 'document_id')
    attempt_id = models.UUIDField()
    document_id = models.UUIDField()
    project_id = models.UUIDField()
    document_version_id = models.UUIDField()

    class Meta:
        managed = False
        db_table = 'submission_items'
