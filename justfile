


run-plantuml-container:
    docker run -d -p 8080:8080 plantuml/plantuml-server:jetty --name plantuml-server

stop-plantuml-container:
    docker stop plantuml-server

# Render C4 diagrams to PNG files in docs/c4/assets/
render-c4-diagrams:
    python scripts/render_c4_diagrams.py

# Render C4 diagrams using online server (no local server needed)
render-c4-diagrams-online:
    python scripts/render_c4_diagrams.py --server https://www.plantuml.com/plantuml