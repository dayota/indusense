"""Archives originales immuables ; les chemins restent confinés à datas/ingestion."""
import codecs
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from .. import catalog as db
from .bronze_storage import normalized_name


def checked_path(root, relative):
    root = Path(root).resolve()
    allowed = root / "datas/ingestion"
    path = root / relative
    if Path(relative).is_absolute() or not path.is_relative_to(allowed) or ".." in path.parts:
        raise HTTPException(409, "Chemin d'archive invalide")
    cursor = root
    for part in path.relative_to(root).parts:
        cursor /= part
        if cursor.is_symlink():
            raise HTTPException(409, "Une archive ne peut pas passer par un lien symbolique")
    return path


def version_directory(connection, version, root):
    preparation = connection.execute(select(db.preparations).where(db.preparations.c.model_version_id == version["id"])).mappings().one()
    relative = preparation["archive_directory"]
    if not relative:
        model = connection.scalar(select(db.models.c.name).where(db.models.c.id == version["model_id"]))
        relative = f"datas/ingestion/{normalized_name(model)}/{version['number']}"
        other = connection.scalar(select(db.preparations.c.model_version_id).where(db.preparations.c.archive_directory == relative))
        if other is not None and other != version["id"]:
            raise HTTPException(409, "Ce nom de dossier d'ingestion appartient déjà à une autre version. Choisis un nom de modèle distinct.")
        connection.execute(db.preparations.update().where(db.preparations.c.model_version_id == version["id"]).values(archive_directory=relative))
    path = checked_path(root, relative)
    path.mkdir(parents=True, exist_ok=True)
    return relative


def input_path(directory, filename):
    """Emplacement unique des sources dans un dossier de version."""
    return str(Path(directory) / 'inputs' / filename)


def digest(stream):
    stream.seek(0)
    value = hashlib.file_digest(stream, "sha256").hexdigest()
    stream.seek(0)
    return value


def open_original(root, archive):
    path = checked_path(root, archive["path"])
    if path.parent.name != 'inputs' or path.name != archive['filename']:
        raise HTTPException(409, "Une source téléversée doit être stockée dans le dossier inputs")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise HTTPException(404, "Archive source introuvable sur disque") from None
    except OSError:
        raise HTTPException(503, "Archive source inaccessible") from None
    stream = os.fdopen(descriptor, "rb")
    try:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size != archive["size_bytes"] or digest(stream) != archive["sha256"]:
            raise HTTPException(409, "L'intégrité de l'archive source ne correspond plus au téléversement")
        return stream
    except BaseException:
        stream.close()
        raise


def save(connection, version, file, root):
    filename = file["filename"]
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(422, "Nom de fichier d'archive invalide")
    by_hash = connection.execute(select(db.source_archives).where(db.source_archives.c.model_version_id == version["id"],
        db.source_archives.c.sha256 == file["sha256"])).mappings().first()
    if by_hash:
        directory = version_directory(connection, version, root)
        if by_hash['path'] != input_path(directory, by_hash['filename']):
            raise HTTPException(409, "L'archive doit être migrée vers le dossier inputs avant utilisation")
        with open_original(root, by_hash): pass
        return by_hash
    by_name = connection.execute(select(db.source_archives).where(db.source_archives.c.model_version_id == version['id'],
        db.source_archives.c.filename == filename)).mappings().first()
    if by_name:
        raise HTTPException(409, f"Une archive différente porte déjà le nom {filename}. Crée une nouvelle version pour la remplacer.")
    directory = version_directory(connection, version, root)
    relative = input_path(directory, filename)
    path = checked_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = bytes(file["content"])
    archive = {"id": file["id"], "model_version_id": version["id"], "filename": filename,
               "sha256": file["sha256"], "size_bytes": len(content), "path": relative}
    if hashlib.sha256(content).hexdigest() != file["sha256"]:
        raise HTTPException(409, "L'empreinte source a changé avant archivage")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Publication atomique sans écraser un original, y compris après interruption.
            os.link(temporary, path)
        except FileExistsError:
            with open_original(root, archive): pass
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    connection.execute(db.source_archives.insert().values(**archive))
    return archive


def history(connection, version_id):
    current = set(connection.scalars(select(db.preparation_files.c.id).where(db.preparation_files.c.model_version_id == version_id)))
    return [{**dict(row), "active": row["id"] in current} for row in connection.execute(select(db.source_archives)
        .where(db.source_archives.c.model_version_id == version_id).order_by(db.source_archives.c.created_at, db.source_archives.c.id)).mappings()]


def get(engine, version_id, archive_id):
    with engine.connect() as connection:
        archive = connection.execute(select(db.source_archives).where(db.source_archives.c.id == archive_id,
            db.source_archives.c.model_version_id == version_id)).mappings().first()
        if archive is None: raise HTTPException(404, "Archive introuvable pour cette version")
        return dict(archive)


def preview(engine, version_id, archive_id, root, encoding):
    archive = get(engine, version_id, archive_id)
    with open_original(root, archive) as stream:
        content = stream.read(128 * 1024)
        truncated = archive["size_bytes"] > len(content)
    try:
        text = codecs.getincrementaldecoder(encoding)(errors="strict").decode(content, final=not truncated)
    except UnicodeError:
        raise HTTPException(422, "Ce fichier ne se décode pas avec cet encodage. Choisis l'encodage de la source ou télécharge l'original.") from None
    return {"filename": archive["filename"], "path": archive["path"], "sha256": archive["sha256"],
            "size_bytes": archive["size_bytes"], "encoding": encoding, "content": text, "truncated": truncated}
