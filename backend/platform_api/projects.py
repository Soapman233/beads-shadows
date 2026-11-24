"""Owner-scoped project versions and private image assets."""
from datetime import datetime, timezone
import io
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import User, current_user
from .db import Base, get_db
from .project_data import CreateProject, RevisionRequest, UpdateProject, validate_project

router = APIRouter()
FILE_LIMIT = 12 * 1024 * 1024
USER_BUDGET = 128 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Asset(Base):
    __tablename__ = 'assets'
    __table_args__ = (Index('ix_assets_owner', 'owner_id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Project(Base):
    __tablename__ = 'projects'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_id', name='uq_projects_import'),
        Index('ix_projects_directory', 'owner_id', 'deleted_at', 'updated_at', 'id'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    request_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProjectVersion(Base):
    __tablename__ = 'project_versions'
    __table_args__ = (UniqueConstraint('project_id', 'revision', name='uq_project_versions_revision'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    counts: Mapped[dict] = mapped_column(JSON, nullable=False)
    bead_count: Mapped[int] = mapped_column(Integer, nullable=False)
    color_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'))
    mask_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


def asset_path(asset_id):
    root = Path(os.environ.get('BEAD_ASSET_DIR', str(Path(__file__).resolve().parents[2] / 'tmp' / 'private-assets')))
    return root / (asset_id + '.png')


def find_asset(db, user, asset_id):
    row = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.owner_id == user.id))
    if row is None:
        raise HTTPException(404, '未找到图片资源')
    return row


@router.post('/assets', status_code=201)
def upload_asset(file: UploadFile = File(...), kind: str = Form(...),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind not in ('source', 'mask', 'finished'):
        raise HTTPException(422, '资源类型无效')
    contents = file.file.read(FILE_LIMIT + 1)
    if len(contents) > FILE_LIMIT:
        raise HTTPException(413, '图片资源超过12MB')
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.format != 'PNG' or not 1 <= image.width <= 1536 or not 1 <= image.height <= 1536:
                raise ValueError()
            w, h = image.size
            image.load()
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, '请选择有效的PNG工作图') from exc
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
    # Use a locking/current read consistently with the competing upload transaction.
    sizes = db.scalars(select(Asset.size).where(Asset.owner_id == user.id).with_for_update()).all()
    if sum(sizes) + len(contents) > USER_BUDGET or len(sizes) >= 512:
        raise HTTPException(413, '账号图片空间不足')
    asset = Asset(id=str(uuid4()), owner_id=user.id, kind=kind, size=len(contents), width=w, height=h)
    path = asset_path(asset.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending')
    try:
        with pending.open('xb') as stream:
            stream.write(contents)
        pending.replace(path)
        db.add(asset)
        db.commit()
    finally:
        pending.unlink(missing_ok=True)
    return {'id': asset.id, 'size': asset.size}


@router.get('/assets/{asset_id}/content')
def download_asset(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = find_asset(db, user, asset_id)
    path = asset_path(asset.id)
    if not path.is_file():
        raise HTTPException(410, '图片资源文件缺失')
    return FileResponse(path, media_type='image/png',
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


def find_project(db, user, project_id, *, lock=False, include_deleted=False):
    query = select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    if not include_deleted:
        query = query.where(Project.deleted_at.is_(None))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    project = db.scalar(query)
    if project is None:
        raise HTTPException(404, '未找到项目')
    return project


def check_revision(project, expected):
    if project.revision != expected:
        raise HTTPException(409, '服务器项目已有新版本，请保留本机副本后重新打开')


def latest_version(db, project):
    # Metadata-only revisions for the trash lifecycle do not duplicate content.
    version = db.scalar(select(ProjectVersion).where(ProjectVersion.project_id == project.id)
                        .order_by(ProjectVersion.revision.desc()).limit(1))
    if version is None:
        raise HTTPException(409, '项目尚无可恢复版本')
    return version


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def project_info(project):
    return {'id': project.id, 'name': project.name, 'revision': project.revision,
            'createdAt': stamp(project.created_at), 'updatedAt': stamp(project.updated_at),
            'deleted': project.deleted_at is not None}


def version_info(version):
    return {'id': version.id, 'revision': version.revision, 'createdAt': stamp(version.created_at),
            'beadCount': version.bead_count, 'colorCount': version.color_count}


def prepare_version(db, user, body):
    source = find_asset(db, user, body.source_id) if body.source_id else None
    mask = find_asset(db, user, body.mask_id) if body.mask_id else None
    if (source and source.kind != 'source') or (mask and mask.kind != 'mask'):
        raise HTTPException(422, '项目图片类型不匹配')
    return validate_project(body.project, (source.width, source.height) if source else None,
                            (mask.width, mask.height) if mask else None)


def append_version(db, user, project, body):
    data, counts = prepare_version(db, user, body)
    db.add(ProjectVersion(id=str(uuid4()), project_id=project.id, revision=project.revision,
                          data=data, counts=dict(counts), bead_count=sum(counts.values()),
                          color_count=len(counts), source_id=body.source_id, mask_id=body.mask_id))


def ensure_room_closed(db, project):
    # Collaboration imports the project models, so resolve this dependency at request time.
    from .collab import active_room

    if active_room(db, project.id, lock=True):
        raise HTTPException(409, '此项目正在协作，请先保存协作版本、结束房间或使用结构更新')


@router.get('/projects')
def list_projects(q: str = Query('', max_length=80), trash: bool = False,
                  page: int = Query(1, ge=1, le=5000), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    query = select(Project).where(Project.owner_id == user.id)
    query = query.where(Project.deleted_at.is_not(None) if trash else Project.deleted_at.is_(None))
    if q.strip():
        query = query.where(Project.name.contains(q.strip(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Project.updated_at.desc(), Project.id.desc()).limit(20).offset((page - 1) * 20))
    return {'items': [project_info(row) for row in rows], 'total': total}

@router.get('/project-imports/{request_id}')
def get_import(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Project).where(Project.owner_id == user.id, Project.request_id == request_id))
    return {'project': project_info(row) if row else None}


@router.post('/projects', status_code=201)
def create_project(body: CreateProject, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
    prior = db.scalar(select(Project).where(Project.owner_id == user.id, Project.request_id == body.request_id)
                      .with_for_update())
    if prior:
        return {**project_info(prior), 'reused': True}
    project = Project(id=str(uuid4()), owner_id=user.id, request_id=body.request_id,
                      name=body.name.strip() or '未命名', revision=1)
    db.add(project)
    db.flush()
    append_version(db, user, project, body)
    response = project_info(project)
    db.commit()
    return response


@router.get('/projects/{project_id}')
def get_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = find_project(db, user, project_id)
    version = latest_version(db, project)
    return {**project_info(project), 'version': version_info(version), 'project': version.data,
            'source_id': version.source_id, 'mask_id': version.mask_id}


@router.patch('/projects/{project_id}')
def update_project(project_id: str, body: UpdateProject, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    project = find_project(db, user, project_id, lock=True)
    check_revision(project, body.expected_revision)
    ensure_room_closed(db, project)
    project.revision += 1
    project.name = body.name.strip() or '未命名'
    project.updated_at = now()
    append_version(db, user, project, body)
    response = project_info(project)
    db.commit()
    return response


@router.get('/projects/{project_id}/versions')
def list_versions(project_id: str, before: int | None = Query(None, ge=1), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    project = find_project(db, user, project_id)
    query = select(ProjectVersion).where(ProjectVersion.project_id == project.id)
    if before is not None:
        query = query.where(ProjectVersion.revision < before)
    return {'items': [version_info(v) for v in db.scalars(query.order_by(ProjectVersion.revision.desc()).limit(20))]}


@router.post('/projects/{project_id}/versions/{version_id}/restore')
def restore_version(project_id: str, version_id: str, body: RevisionRequest,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = find_project(db, user, project_id, lock=True)
    check_revision(project, body.expected_revision)
    ensure_room_closed(db, project)
    snapshot = db.scalar(select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project.id))
    if not snapshot:
        raise HTTPException(404, '未找到版本')
    project.revision += 1
    project.updated_at = now()
    db.add(ProjectVersion(id=str(uuid4()), project_id=project.id, revision=project.revision, data=snapshot.data,
                          counts=snapshot.counts, bead_count=snapshot.bead_count, color_count=snapshot.color_count,
                          source_id=snapshot.source_id, mask_id=snapshot.mask_id))
    response = project_info(project)
    db.commit()
    return response


@router.post('/projects/{project_id}/trash')
@router.post('/projects/{project_id}/untrash')
def change_trash(project_id: str, body: RevisionRequest, request: Request,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = find_project(db, user, project_id, lock=True, include_deleted=True)
    check_revision(project, body.expected_revision)
    trash = request.url.path.endswith('/trash')
    if trash != bool(project.deleted_at):
        ensure_room_closed(db, project)
        project.deleted_at = now() if trash else None
        project.updated_at = now()
        project.revision += 1
    response = project_info(project)
    db.commit()
    return response
