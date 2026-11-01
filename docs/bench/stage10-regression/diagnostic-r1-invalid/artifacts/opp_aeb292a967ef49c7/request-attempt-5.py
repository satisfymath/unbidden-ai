{
 "method": "PUT",
 "path": "/api/v1/spool/{value}/measure",
 "query": {},
 "body": {
  "weight": 500
 },
 "values_sql": "BEGIN READ ONLY; SELECT id FROM spool ORDER BY id LIMIT 30; COMMIT;",
 "why": "Measuring a spool loads its filament vendor then all filaments of that vendor, reading filament by vendor_id.",
 "table": "filament",
 "column": "vendor_id"
}