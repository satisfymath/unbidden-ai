{
 "method": "PUT",
 "path": "/api/v1/spool/{value}/measure",
 "query": {},
 "body": {
  "weight": 500
 },
 "values_sql": "BEGIN READ ONLY; SELECT id FROM spool ORDER BY id LIMIT 30; COMMIT;",
 "why": "Measuring a spool loads its filament vendor and reads filament by vendor_id to return the spool view.",
 "table": "filament",
 "column": "vendor_id"
}