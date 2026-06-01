# python-updater

PyQt6 기반으로 구현된 GitHub 릴리스 자동 업데이트 GUI 프로그램입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
python -m python_updater.main -v v0.0.0
```

## 환경 변수

- `UPDATER_REPO_OWNER` (기본값: `q09009`)
- `UPDATER_REPO_NAME` (기본값: `qt-updater`)
- `UPDATER_TARGET_EXE` (기본값: `MyProgram.exe`)

## 동작 요약

1. GitHub Releases API (`/releases/latest`)에서 최신 태그 조회
2. 현재 버전과 비교 후 업데이트 필요 여부 판단
3. 릴리스 에셋에서 `.exe` 우선, 없으면 `.zip` 선택 후 다운로드
4. `.exe`는 `MyProgram_new.exe`로 저장 후 기존 실행 파일 교체
5. `.zip`은 Windows에서 압축 해제 후 `data`, `logs` 경로를 보존하면서 파일 반영
