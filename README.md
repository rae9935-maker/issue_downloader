# issue_downloader

국회입법조사처([nars.go.kr](https://www.nars.go.kr/report/list.do?cmsCode=CM0018)) 보고서 목록을 받아 하나의 PDF로 합칩니다.

목록의 [다운로드]와 같은 주소(`fileDownload2.do?doc_id=...`)를 쓰고, 받은 파일을 목록 순서대로 붙입니다. 합친 파일에는 글 제목 북마크가 들어갑니다.

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
