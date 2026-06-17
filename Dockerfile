FROM python:3.12-slim

ARG ROBOT_VERSION=1.9.7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OCA_DATABASE_URL=sqlite:////data/oca.sqlite3 \
    OCA_LITERATURE_BASE_DIR=/data/literature \
    OCA_LITERATURE_PDF_DIR=/data/literature/Paper-PDF \
    OCA_LITERATURE_GENERATED_MD_DIR=/data/literature/Markdown \
    OCA_LITERATURE_REPOSITORY_PATH=/data/literature/papers \
    OCA_LITERATURE_COMBINED_OUTPUT_FILE=/data/literature/combined_literature.md \
    OCA_ODK_HOME=/odk \
    OCA_LOCAL_ONTOLOGY_PATH=/ontology \
    OCA_PPO_ODK_ONTOLOGY_PATH=/odk/ontology/src/ontology

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl default-jre-headless git make \
    && curl -fsSL "https://github.com/ontodev/robot/releases/download/v${ROBOT_VERSION}/robot.jar" -o /usr/local/lib/robot.jar \
    && printf '#!/bin/sh\nexec java -jar /usr/local/lib/robot.jar "$@"\n' > /usr/local/bin/robot \
    && chmod +x /usr/local/bin/robot \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY backend /app/backend
COPY ontology_curation_assistant /app/ontology_curation_assistant
COPY zotero_lit_md /app/zotero_lit_md
COPY prompts /app/prompts
COPY schemas /app/schemas

RUN pip install --no-cache-dir -e ".[dev]"

RUN mkdir -p /data/literature /data/projects /ontology /odk

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
