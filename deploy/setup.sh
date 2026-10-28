#!/usr/bin/env bash
# ==============================================================================
# TarkApp Quick Setup & Deployment Script for Zone VPS
# Target host: uvn-235-67.ams01.zonevs.eu
# ==============================================================================

set -e

# ANSI Color Codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}       TarkApp Zone VPS Automated Deployment        ${NC}"
echo -e "${CYAN}====================================================${NC}"

# 1. Verify Docker & Compose installation
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}[!] Docker not found. Installing Docker engine...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}[✓] Docker installed successfully.${NC}"
else
    echo -e "${GREEN}[✓] Docker is installed: $(docker --version)${NC}"
fi

# Detect compose command
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}[✗] docker compose not found. Please install the docker-compose-plugin.${NC}"
    exit 1
fi
echo -e "${GREEN}[✓] Using compose: $($DOCKER_COMPOSE version)${NC}"

# 2. Check environment configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}[!] backend/.env not found. Creating from backend/.env.example...${NC}"
    cp backend/.env.example backend/.env
    echo -e "${RED}[WARNING] Please edit backend/.env and set your GEMINI_API_KEY!${NC}"
    echo -e "${YELLOW}Press Enter to continue or Ctrl+C to edit backend/.env now...${NC}"
    read -r
fi

# 3. Build & start containers
echo -e "${CYAN}[*] Building and starting TarkApp Docker containers...${NC}"
$DOCKER_COMPOSE down --remove-orphans || true
$DOCKER_COMPOSE build backend
$DOCKER_COMPOSE up -d

echo -e "${CYAN}[*] Waiting for backend service health check...${NC}"
for i in {1..30}; do
    if curl -s -f http://127.0.0.1:8080/health > /dev/null 2>&1; then
        echo -e "${GREEN}[✓] Backend service is healthy!${NC}"
        break
    fi
    sleep 2
    if [ "$i" -eq 30 ]; then
        echo -e "${RED}[✗] Healthcheck timeout. Inspecting logs:${NC}"
        $DOCKER_COMPOSE logs backend
        exit 1
    fi
done

# 4. Verify Nginx response
if curl -s -f http://127.0.0.1/health > /dev/null 2>&1; then
    echo -e "${GREEN}[✓] Nginx reverse-proxy is routing traffic successfully!${NC}"
fi

echo -e "${CYAN}====================================================${NC}"
echo -e "${GREEN}🎉 TarkApp successfully deployed on Zone VPS!${NC}"
echo -e "   Landing page: http://uvn-235-67.ams01.zonevs.eu"
echo -e "   API Docs:     http://uvn-235-67.ams01.zonevs.eu/docs"
echo -e "   Healthcheck:  http://uvn-235-67.ams01.zonevs.eu/health"
echo -e "${CYAN}====================================================${NC}"
echo -e "${YELLOW}Useful Maintenance Commands:${NC}"
echo -e "  • Show real-time logs:     ${DOCKER_COMPOSE} logs -f"
echo -e "  • Generate PRO keys:       ${DOCKER_COMPOSE} exec backend python scripts/generate_keys.py --count 10 --days 30"
echo -e "  • Check database contents: ${DOCKER_COMPOSE} exec backend python -c \"from app.database import SessionLocal; from app.models.license import AccessKey; print('Total keys:', SessionLocal().query(AccessKey).count())\""
echo -e "  • Restart stack:           ${DOCKER_COMPOSE} restart"
echo -e "${CYAN}====================================================${NC}"
