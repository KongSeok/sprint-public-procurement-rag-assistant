Timestamp: 2026-08-31 18:30
Context: refined98 9,331-chunk KURE semantic index build

Issues
1) 초기 outer embedding call batch 32는 provider 내부 batch 32와 중복되어 호출 오버헤드가 커졌고, 실행을 중단한 뒤 재개해야 했다.

Resolution
- provider batch는 32로 유지하고 embed_chunks outer call batch만 512로 조정했다. content-addressed cache에서 3,140 hit/6,191 miss로 재개한 뒤 9,331행 index를 완성했고, 재실행 9,331/9,331 hit와 동일 vector SHA를 확인했다.

Prevention
- provider micro-batch와 orchestration batch를 별도 설정·기록하고, 전수 실행 전 소량 throughput smoke로 ETA를 확인한다.
