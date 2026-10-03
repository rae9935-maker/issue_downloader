# issue_downloader

국회입법조사처([nars.go.kr](https://www.nars.go.kr/report/list.do?cmsCode=CM0018)) 보고서 목록을 받아 하나의 PDF로 합칩니다.

목록의 [다운로드]와 같은 주소(`fileDownload2.do?doc_id=...`)를 쓰고, 받은 파일을 목록 순서대로 붙입니다. 합친 파일에는 글 제목 북마크가 들어갑니다.

## 사용

```bash
pip install -r requirements.txt
python download_merge.py --limit 100
```

결과 파일은 `output/nars_merged.pdf` 입니다. 개별 PDF는 `downloads/`에 남고, 다시 실행하면 이미 받은 파일은 건너뜁니다.

```bash
# 이슈와논점 최신 100건 (cmsCode=CM0018, 주제 전체)
python download_merge.py --limit 100 --output output/issues_100.pdf

# 재정금융(categoryId=b1)만 최신 100건
python download_merge.py --category-id b1 --limit 100

# 재정금융, 법제사법을 각각 PDF로
python download_merge.py --category-id b1,a2 --limit 100

# 사이트에 있는 주제마다 PDF를 따로
python download_merge.py --split-by-category --limit 100

# 주제 코드 확인
python download_merge.py --list-categories

# 연구보고서 최신 100건
python download_merge.py --cms-code CM0043 --limit 100 --output output/research_100.pdf

# 제목에 '연금'이 들어간 글 30건
python download_merge.py --keyword 연금 --limit 30 --output output/pension.pdf

# 11페이지부터 이어서 50건
python download_merge.py --start-page 11 --limit 50 --output output/issues_page11.pdf
```

`--limit`은 주제마다 적용됩니다. 주제를 지정하지 않으면 `output/nars_merged.pdf` 하나입니다. 주제를 지정하면 `output/{categoryId}_{이름}.pdf`이고, 개별 파일은 `downloads/{categoryId}/`에 둡니다.

한 페이지에 10건입니다. 100건이면 목록 10페이지입니다. 이슈와논점의 주제는 목록 화면과 같습니다. `b1`은 재정금융입니다. `--list-categories`가 현재 코드를 보여 줍니다.

동시 다운로드는 기본 4개입니다. 사이트가 느려지면 `--workers 2`로 낮추세요.
