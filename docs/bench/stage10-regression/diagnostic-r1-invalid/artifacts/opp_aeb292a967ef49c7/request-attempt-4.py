{
 "method": "PUT",
 "path": "/api/v1/spool/{value}/measure",
 "query": {},
 "body": {
  "weight": 500
 },
 "values_sql": "BEGIN READ ONLY; SELECT id FROM spool ORDER BY id LIMIT 100; COMMIT;",
 "why": "Measuring a spool loads its filament then reads filament by vendor_id to resolve the vendor for the response.",
 "table": "filament",
 "column": "vendor_id"
}