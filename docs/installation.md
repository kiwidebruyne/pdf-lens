# PDF Lens 설치 안내

## 처음 사용하는 분

GitHub 가입이나 저장소 다운로드는 필요하지 않습니다. 로그인된 Codex 데스크톱 앱에서 내 컴퓨터의 파일을 다루는 작업을 열고, 아래 문장을 보내세요. 설치 명령은 Codex가 실행합니다.

```text
PDF Lens를 설치해 줘. 공식 안내는 https://raw.githubusercontent.com/kiwidebruyne/pdf-lens/main/docs/installation.md 에 있어. 최신 공개 안정판의 ZIP과 체크섬을 확인해서 이 컴퓨터에 설치해 줘. 정상 설치를 확인한 뒤 설치된 버전과 다음 사용 방법을 알려 줘. 내가 터미널 명령을 직접 입력하지 않도록 처리해 줘.
```

인터넷에 연결한 상태로 설치 완료까지 기다립니다. Codex가 설치된 버전과 정상 설치 확인을 알려 주면 영어 텍스트 PDF를 첨부하고 읽을 범위를 말하세요. **첫 사용은 2–5쪽을 권합니다.** 클릭·드래그·저장·수정까지의 예시는 [처음부터 따라 하는 사용 안내](../README.md)에 있습니다.

Windows에서는 필요한 Microsoft 런타임이 없을 때 관리자 승인 창이 나타날 수 있습니다. Codex가 실제 원인과 Microsoft 서명 확인 결과를 설명하면 내용을 확인해 승인하세요. 확인된 환경과 아직 시험하지 않은 환경은 [검증 현황](verification.md)에 있습니다.

## Codex가 수행할 절차

아래는 설치를 대신 수행하는 Codex용 지침입니다. 사용자에게 Terminal·PowerShell을 직접 열거나 Python, Git, Node.js, uv를 직접 설치하라고 요구하지 마세요. 초기 설치와 업데이트에는 인터넷이 필요합니다.

### 1. 공개 안정판 다운로드 및 검증

1. [GitHub의 최신 정식 릴리스](https://github.com/kiwidebruyne/pdf-lens/releases/latest)를 확인합니다. 초안과 시험판은 제외합니다. `main` 체크아웃을 안정판 대신 설치하지 마세요.
2. 릴리스 자산 `pdf-lens-VERSION.zip`과 `pdf-lens-VERSION.zip.sha256`을 모두 내려받습니다. `VERSION`에는 해당 릴리스의 실제 버전을 넣습니다. 공개 다운로드는 GitHub 계정이나 `gh` 인증을 요구하지 않습니다.
3. ZIP의 SHA-256이 체크섬 파일과 정확히 일치하는지 확인한 후 임시 폴더에 풉니다. 불일치하면 실행하지 마세요. 태그 버전과 압축 파일 안의 `VERSION`도 대조합니다.
4. 설치 성공을 확인할 때까지 압축을 푼 릴리스 폴더를 유지합니다. 해당 릴리스에 포함된 bootstrap을 사용합니다.

### 2. 해당 OS의 설치 프로그램 실행

macOS:

```sh
sh /path/to/extracted/pdf-lens/scripts/bootstrap.sh --source /path/to/extracted/pdf-lens
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\path\to\extracted\pdf-lens\scripts\bootstrap.ps1 -Source C:\path\to\extracted\pdf-lens
```

예시 경로를 실제 추출 경로로 바꿉니다. 설정된 `CODEX_HOME`이 있으면 그 위치를 사용합니다. 기본은 macOS의 `~/.codex`, Windows의 `%USERPROFILE%\.codex`입니다. bootstrap은 PDF Lens 전용 폴더 안에 uv, CPython 3.13, PDF 처리 도구와 검사 브라우저를 설치합니다. 시스템 Python·Git·Node.js는 필요하지 않습니다.

Windows bootstrap은 관리형 PDF 렌더러에서 Microsoft Visual C++ 런타임 DLL 누락이 확인될 때만 공식 설치 프로그램을 받습니다. Microsoft 서명을 확인한 뒤 관리자 승인을 요청합니다. 설치가 실패하면 기존 정상 설치를 보존하고 실제 오류를 설명하세요.

### 3. 설치 확인 및 사용자 안내

macOS:

```sh
codex_home=${CODEX_HOME:-"$HOME/.codex"}
sh "$codex_home/skills/pdf-lens/scripts/bootstrap.sh" --state
```

Windows PowerShell:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
powershell -ExecutionPolicy Bypass -File "$codexHome\skills\pdf-lens\scripts\bootstrap.ps1" -Action state
```

`installed`가 true인지, 활성 버전·전용 런타임 경로·소스 스냅샷이 존재하는지 확인합니다. 정상 설치가 확인됐을 때만 성공이라고 알립니다. 사용자에게 **설치된 버전**, **PDF 첨부 방법**, **인쇄 쪽수와 PDF 순번 중 어느 기준인지 말해야 한다는 점**을 안내하세요. 필요하면 새 작업에서 설치된 스킬을 다시 불러오게 합니다.

새 문서의 처리는 설치된 `scripts/run.py`를 사용합니다. 새 작업 폴더를 준비할 때 최신 안정판을 확인하며, 진행 중인 작업은 기록된 버전과 소스 스냅샷으로 재개합니다. 실패한 업데이트 후 가능한 경우 기존 정상 버전을 사용합니다. 자세한 업데이트·재개·제거 절차는 [실행 환경 안내](../references/setup.md)에 있습니다.

## 설치 후 알아둘 점

- 텍스트 추출이 가능한 영어 PDF를 지원합니다. 스캔 PDF OCR은 지원하지 않습니다.
- 원문 리더가 먼저 열리고 번역이 문장별로 반영됩니다. 원문만 보이는 화면을 완성본이라고 전달하지 마세요.
- 전체 검사와 빌드가 끝나면 최종 HTML 경로를 전달합니다. 사용자는 이 파일을 더블 클릭해 오프라인으로 읽을 수 있습니다.
- **오프라인은 완성본을 읽는 방식입니다.** 제작 중 Codex가 읽는 텍스트·이미지는 모델 처리 과정에서 클라우드로 전달될 수 있습니다. 자료가 절대로 기기 밖으로 나가지 않는다고 설명하지 마세요.
- 사용자 PDF·작업 폴더·생성된 HTML은 공개 저장소나 릴리스에 넣지 마세요. 사용자가 공유하려면 원문과 번역의 권한을 별도로 확인해야 합니다.
