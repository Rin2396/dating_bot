FROM python:3.11

WORKDIR /app
ENV PYTHONPATH=/app/src


COPY pyproject.toml poetry.lock ./
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-root

COPY ./src ./src

CMD ["echo", "Base image built. Override CMD in docker-compose."]
