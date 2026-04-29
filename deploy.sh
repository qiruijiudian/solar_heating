#!/bin/bash

set -e

echo "=== Solar Heating Deployment Script ==="
echo ""

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo "Error: Docker is not installed"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        echo "Error: docker-compose is not installed"
        exit 1
    fi
}

stop_container() {
    echo "Stopping existing container..."
    docker-compose down 2>/dev/null || true
}

build_image() {
    echo "Building Docker image..."
    docker-compose build --no-cache
}

start_container() {
    echo "Starting container..."
    docker-compose up -d
}

show_logs() {
    echo ""
    echo "Container started. Showing logs (Ctrl+C to exit)..."
    echo ""
    docker-compose logs -f --tail=100
}

check_status() {
    echo ""
    echo "=== Container Status ==="
    docker-compose ps
    echo ""
    echo "=== Resource Usage ==="
    docker stats --no-stream solar-heating-app 2>/dev/null || echo "Container not running"
}

cleanup_zombies() {
    echo "Cleaning up zombie processes..."
    pkill -f "urllib.request.urlopen" 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
}

main() {
    check_docker
    cleanup_zombies
    stop_container
    build_image
    start_container
    
    echo ""
    echo "Waiting for container to start (30 seconds)..."
    sleep 30
    
    check_status
    show_logs
}

main "$@"
