#!/bin/bash

FILE=./docker-compose.yaml

docker compose -f "$FILE" down -v
docker compose -f "$FILE" up -d --build
