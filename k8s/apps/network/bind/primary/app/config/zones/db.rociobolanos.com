; SOA Records
$TTL 1h
$ORIGIN rociobolanos.com.
@ IN SOA ns.rociobolanos.com. admin.rociobolanos.com. (
  1788000000        ; serial number; date +%s
  1m                ; refresh period
  1m                ; retry period
  14d               ; expire time
  0                 ; minimum ttl
)

; NS Records
@                        IN  NS ns
ns                       IN  A  10.45.0.55
@                        IN  NS ns2
ns2                      IN  A  10.45.0.55
