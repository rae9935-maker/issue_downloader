# issue_downloader

국회입법조사처([nars.go.kr](https://www.nars.go.kr/report/list.do?cmsCode=CM0018)) 보고서 목록을 받아 하나의 PDF로 합칩니다.

목록의 [다운로드]와 같은 주소(`fileDownload2.do?doc_id=...`)를 쓰고, 받은 파일을 목록 순서대로 붙입니다. 합친 파일에는 글 제목 북마크가 들어갑니다.

## 안드로이드 태블릿

태블릿에는 터미널 대신 버튼 화면을 씁니다. 주제, 시작 번호, 끝 번호만 고르면 개수를 계산해서 그 구간을 하나의 PDF로 합칩니다. PC용 명령과 같은 규칙입니다. 이미 받은 문서는 `manifest.json`을 보고 건너뜁니다.

Play 스토어의 Termux는 오래된 빌드라 동작하지 않는 경우가 많습니다. [F-Droid의 Termux](https://f-droid.org/packages/com.termux/)를 설치하세요.

Termux를 연 뒤 한 번만 저장소 권한을 허용합니다.

```bash
pkg update && pkg install -y python git
termux-setup-storage
```

저장소 폴더를 허용하면 합친 PDF가 태블릿의 내 파일 앱 `Download/nars/pdf`에 들어갑니다. 그 다음 이 저장소를 받아 화면을 켭니다.

```bash
git clone https://github.com/rae9935-maker/issue_downloader.git
cd issue_downloader
pip install -r requirements.txt
python tablet_server.py
```

Chrome에서 `http://127.0.0.1:8765` 을 엽니다. `localhost` 대신 `127.0.0.1`을 적어야 태블릿의 Termux에 연결됩니다.

1. 목록에서 이슈와논점 또는 연구보고서를 고릅니다.
2. 주제 버튼을 누릅니다. 재정금융은 `b1`입니다.
3. 시작 번호와 끝 번호를 넣습니다. `10`과 `59`이면 50개입니다.
4. `이 구간 받기`를 누릅니다. 진행 줄에 `3 / 50`처럼 올라갑니다.
5. 끝나면 `합친 PDF 열기`를 누릅니다. Chrome 뷰어에서 바로 열리고, 저장소 권한을 허용했다면 Download 폴더에도 있습니다.
6. 번호가 다음 구간으로 바뀝니다. 예를 들어 10–59 다음은 60–109입니다. 다시 받기만 누르면 됩니다.

받는 동안 Termux 알림을 지우지 마세요. 화면 서버는 `termux-wake-lock`이 있으면 화면이 꺼져도 받기를 이어 갑니다. 멈추려면 Termux에서 Ctrl+C를 누릅니다. 다음 실행에서 같은 구간을 다시 누르면 이미 받은 파일은 건너뜁니다.

한 번에 400개보다 많은 구간은 받지 않습니다. 태블릿 메모리를 위해 50개 안팎으로 나누세요. 동시 다운로드는 2개입니다.

같은 Termux에서 명령을 직접 쳐도 됩니다.

```bash
python download_merge.py --category-id b1 --start 10 --end 59
```

버튼 화면을 쓰지 않으면 PDF는 `output/`에, 개별 파일은 `downloads/`에 남습니다. 저장소 권한을 허용한 상태에서 `python tablet_server.py`로 켠 경우에만 `Download/nars/`로 들어갑니다.

## 사용

```bash
pip install -r requirements.txt
python download_merge.py --category-id b1 --start 10 --end 59
```

주제와 시작·끝 번호만 지정하면 됩니다. 개수는 `끝 - 시작 + 1`이라 `--start 10 --end 59`는 50개이고, `--start 1 --end 200`은 200개입니다. 100개로 따로 적을 필요는 없습니다. `--range 10-59`는 같은 뜻입니다.

목록 맨 앞이 1번째입니다. 받은 파일은 `downloads/`에 남고, `manifest.json`에 문서 id를 기록합니다. 같은 문서는 구간이 겹쳐도 다시 받지 않습니다.

```bash
# 재정금융(categoryId=b1) 10~59번째, 50개
python download_merge.py --category-id b1 --start 10 --end 59

# 이어서 60~109번째. 앞에서 받은 파일이 있으면 건너뜁니다.
python download_merge.py --category-id b1 --start 60 --end 109

# 같은 구간을 한 줄로
python download_merge.py --category-id b1 --range 10-59

# 재정금융, 법제사법을 같은 구간으로 각각 PDF
python download_merge.py --category-id b1,a2 --start 1 --end 50

# 시작·끝 없이 실행하면 앞에서부터 100개
python download_merge.py --limit 100

# 사이트에 있는 주제마다, 각 주제의 1~100번째
python download_merge.py --split-by-category --limit 100

# 주제 코드 확인
python download_merge.py --list-categories

# 연구보고서 최신 100건
python download_merge.py --cms-code CM0043 --limit 100 --output output/research_100.pdf

# 제목에 '연금'이 들어간 글 30건
python download_merge.py --keyword 연금 --limit 30 --output output/pension.pdf
```

시작·끝 번호는 주제마다 적용됩니다. 합본 경로를 생략하면 `output/{categoryId}_{이름}_{시작}-{끝}.pdf`입니다. 주제가 하나이고 `--output`을 주면 그 경로를 그대로 씁니다. 개별 파일은 `downloads/{categoryId}/0010_...pdf`처럼 목록 순번으로 저장됩니다.

한 페이지에 10건입니다. 100건이면 목록 10페이지입니다. 이슈와논점의 주제는 목록 화면과 같습니다. `b1`은 재정금융입니다. `--list-categories`가 현재 코드를 보여 줍니다.

동시 다운로드는 기본 4개입니다. 사이트가 느려지면 `--workers 2`로 낮추세요.
