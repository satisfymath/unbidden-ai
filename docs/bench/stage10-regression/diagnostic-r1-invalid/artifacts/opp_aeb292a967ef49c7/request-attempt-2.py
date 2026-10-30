{
 "method": "PUT",
 "path": "/api/v1/spool/{value}/measure",
 "query": {},
 "body": {
  "weight": 500
 },
 "values_sql": "BEGIN READ ONLY; SELECT id FROM spool ORDER BY id; COMMIT;",
 "why": "Measuring a spool loads its filament and then reads filament by vendor_id to resolve the vendor relation for the response.",
 "table": "filament",
 "column": "vendor_id"
}