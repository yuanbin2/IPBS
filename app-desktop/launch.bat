@echo off
echo Launching Knowledge Agent Desktop...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:5173 --window-size=1400,900 --window-position=100,100 --user-data-dir="%~dp0.edge-profile"
echo Done!