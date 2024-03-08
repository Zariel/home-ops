-- udp/tcp dns listening
setLocal("0.0.0.0:5353", {})

-- enable prometheus
webserver("0.0.0.0:8083")
setWebserverConfig({
  statsRequireAuthentication = false,
  acl = "10.42.0.0/16, 127.0.0.0/8"
})
setAPIWritable(false)

newServer({
  address = "10.0.0.1",
  pool = "unifi",
  checkName = "unifi",
  maxCheckFailures = 3,
  rise = 3,
  healthCheckMode = "auto",
  checkInterval = 1,
})

-- Local Bind
newServer({
  address = "10.43.53.9",
  pool = "bind",
  checkName = "ns.cbannister.xyz",
  maxCheckFailures = 3,
  rise = 3,
  healthCheckMode = "auto",
  checkInterval = 1,
})

-- Local Blocky
newServer({
  address = "10.43.53.10",
  pool = "blocky",
  healthCheckMode = "lazy",
  checkInterval = 10,
  maxCheckFailures = 3,
  lazyHealthCheckFailedInterval = 30,
  rise = 2,
  lazyHealthCheckThreshold = 30,
  lazyHealthCheckSampleSize = 100,
  lazyHealthCheckMinSampleCount = 10,
  lazyHealthCheckMode = 'TimeoutOnly',
  useClientSubnet = true,
})
-- PiHole will be given requester IP
setECSSourcePrefixV4(32)

-- CloudFlare DNS over TLS
newServer({
  address = "1.1.1.1:853",
  tls = "openssl",
  subjectName = "cloudflare-dns.com",
  validateCertificates = true,
  checkInterval = 10,
  checkTimeout = 2000,
  pool = "cloudflare"
})
newServer({
  address = "1.0.0.1:853",
  tls = "openssl",
  subjectName = "cloudflare-dns.com",
  validateCertificates = true,
  checkInterval = 10,
  checkTimeout = 2000,
  pool = "cloudflare"
})

-- Enable caching
pc = newPacketCache(1000000, {
  maxTTL = 86400,
  minTTL = 0,
  temporaryFailureTTL = 60,
  staleTTL = 60,
  dontAge = false
})
-- getPool("blocky"):setCache(pc)
getPool("cloudflare"):setCache(pc)

-- addAction(AllRule(), LogAction("", false, false, true, false, false))
-- addResponseAction(AllRule(), LogResponseAction("", false, true, false, false))

-- this will send this domain to the bind server
addAction('cbannister.xyz', PoolAction('bind'))
addAction('unifi', PoolAction('unifi'))

addAction("10.0.0.0/21", PoolAction("cloudflare"))  -- lan
addAction("192.168.1.0/24", PoolAction("blocky"))   -- home vlan
addAction("192.168.42.0/24", PoolAction("cloudflare"))  -- servers vlan
addAction("10.1.3.1/24", PoolActions("blocky"))  -- iot
