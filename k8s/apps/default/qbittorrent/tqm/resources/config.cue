package tqm

import (
	"strings"
	"list"
)

#tracker: {
	name!: string
	url!: string | [string, ...string]
	seedDays?: number & >0
	ratio?:    number & >0
}

#trackers: [#tracker, ...#tracker]
#tag: {
	name!: string
	mode:  *"full" | "add" | "remove"
	update!: [string, ...string]
}

clients: qb: {
	download_path: "/data/downloads/torrents/complete"
	enabled:       true
	filter:        "default"
	type:          "qbittorrent"
	url:           "http://qbittorrent.default.svc.cluster.local"
}

filters: [string]: {
	tag: [...#tag]
	remove: [...string]
}

filters: default: {
	MapHardlinksFor: ["retag"]
	ignore: [
		"IsTrackerDown()",
		"Downloaded == false && !IsUnregistered()",
		"SeedingHours < 26 && !IsUnregistered()",
	]
}

#arrCats: [...string] & list.FlattenN([
	for f in ["sonarr", "radarr"] {
		["\(f)", "\(f)-imported"]
	},
], 1)

filters: default: tag: [
	{name: "added:1d", update: ["AddedDays < 7"]},
	{name: "added:7d", update: ["AddedDays >= 7 && AddedDays < 14"]},
	{name: "added:14d", update: ["AddedDays >= 14 && AddedDays < 30"]},
	{name: "added:30d", update: ["AddedDays >= 30 && AddedDays < 180"]},
	{name: "added:180d", update: ["AddedDays >= 180"]},
	{name: "tracker-down", update: ["IsTrackerDown()"]},
	{name: "unregistered", update: ["IsUnregistered()"]},
	{
		name: "not-linked"
		let cats = [for u in #arrCats {"\"\(u)\""}]
		update: ["HardlinkedOutsideClient == false && Label in [\(strings.Join(cats, ","))]"]},

	for t in #trackers {
		name: "site:\(t.name)"
		if (t.url & string) != _|_ {
			update: ["TrackerName == \"\(t.url)\""]
		}
		if (t.url & [...string]) != _|_ {
			let urls = [for u in t.url {"\"\(u)\""}]
			update: ["TrackerName in [\(strings.Join(urls, ", "))]"]
		}
	},
]

filters: default: remove: [
	for t in #trackers if t.seedDays != _|_ || t.ratio != _|_ {
		if t.seedDays != _|_ && t.ratio != _|_ {
			"HasAllTags(\"site:\(t.name)\") && (Ratio > \(t.ratio) || SeedingDays >= \(t.seedDays))"
		}
		if t.seedDays != _|_ && t.ratio == _|_ {
			"HasAllTags(\"site:\(t.name)\") && SeedingDays >= \(t.seedDays)"
		}
		if t.seedDays == _|_ && t.ratio != _|_ {
			"HasAllTags(\"site:\(t.name)\") && Ratio > \(t.ratio)"
		}
	},
]
