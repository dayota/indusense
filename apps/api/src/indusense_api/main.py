from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from indusense_ingestion.paths import project_root

from .database import create_database_engine
from .monitoring import instrument
from .routers import health, workflow, silver, bronze


def create_app(engine=None, resource_root=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine if engine is not None else create_database_engine()
        app.state.resource_root = project_root(resource_root)
        from .services import bronze_execution
        app.state.bronze_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bronze")
        try:
            bronze_execution.resume(app.state.engine, app.state.resource_root, app.state.bronze_executor)
            yield
        finally:
            app.state.bronze_executor.shutdown(wait=True)
            if engine is None:
                app.state.engine.dispose()

    app = FastAPI(
        title="InduSense",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        max_body_size=1024 * 1024,
    )
    app.include_router(health.router)
    app.include_router(workflow.router)
    app.include_router(silver.router)
    app.include_router(bronze.router)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Base indisponible ou migrations à appliquer. Vérifie l’état de la préparation avant de relancer une création."
            },
        )

    instrument(app)
    return app


app = create_app()
