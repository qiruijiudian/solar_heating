@echo off
echo Building Solar Heating Docker image...
docker-compose build

echo Starting Solar Heating container...
docker-compose up -d

echo Checking container status...
docker-compose ps

echo.
echo Solar Heating application is running!
echo Access the application at: http://localhost:8003
echo.
echo To view logs: docker-compose logs -f
echo To stop: docker-compose down
pause
