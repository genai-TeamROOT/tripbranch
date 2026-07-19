# app 패키지 최상위 마커.
# 실제 로직은 없음 - 이 파일이 있어야 `import app...`, pytest의 rootdir 자동 삽입,
# `pip install -e .`의 패키지 탐색(pyproject.toml의 packages.find)이 정상 동작한다.

