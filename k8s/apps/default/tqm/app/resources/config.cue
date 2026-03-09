package tqm

import (
	"strings"
	"list"
	"time"
)

#tracker: {
	name!: string
	url!: string | [...string] & list.MinItems(1)
	seedDays?:    number & >0
	ratio?:       number & >0
	minSeedDays?: number & >0
	tags?: [...string] & list.MinItems(1)
}

#trackers: [...#tracker] & list.MinItems(1)
#tag: {
	name!: string
	mode:  *"full" | "add" | "remove"
	update!: [...string] & list.MinItems(1)
}

_#trackerMatchByName: {
	for t in #trackers {
		if (t.url & string) != _|_ {
			"\(t.name)": "TrackerName == \"\(t.url)\""
		}
		if (t.url & [...string]) != _|_ {
			let urls = [for u in t.url {"\"\(u)\""}]
			"\(t.name)": "TrackerName in [\(strings.Join(urls, ", "))]"
		}
	}
}

_#trackerTagSet: {
	for t in #trackers if (t.tags & [...string]) != _|_ {
		for tag in t.tags {
			"\(tag)": true
		}
	}
}

clients: qb: {
	download_path: "/data/downloads/torrents/complete"
	enabled:       true
	filter:        "default"
	type:          "qbittorrent"
	url:           "http://qbittorrent.default.svc.cluster.local"
}

#orphan: {
	grace_period?: string & time.Duration()
	ignore_paths?: [...string]
}

filters: [string]: {
	bypassIgnoreIfUnregistered?: bool
	MapHardlinksFor: [..."retag" | "clean"] // ?

	tag: [...#tag]
	remove: [...string]
	orphan?: #orphan
	ignore: [...string]
}

bypassIgnoreIfUnregistered: true

_#ignoreCats: [
	"music",
	"games",
	"shared",
	"upload",
	"manual",
]

filters: default: {
	MapHardlinksFor: ["retag", "clean"]
	ignore: [
		"IsTrackerDown()",
		"Downloaded == false",
		"SeedingHours < 26",
		"HardlinkedOutsideClient == true",
		for cat in _#ignoreCats {
			"Label startsWith \"\(cat)\""
		},

		// Protect unlinked torrents until minSeedDays is met (grace period before removal)
		for t in #trackers if t.minSeedDays != _|_ {
			"HasAllTags(\"site:\(t.name)\", \"not-linked\") && SeedingDays < \(t.minSeedDays)"
		},
	]
	orphan: {
		grace_period: "1h"
		ignore_paths: [
			for cat in _#ignoreCats {
				"/data/downloads/torrents/complete/\(cat)"
			},
		]
	}
}

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
		let cats = [for u in ["sonarr-imported", "radarr-imported", "cross-seed", "sonarr", "radarr"] {"\"\(u)\""}]
		update: [
			"HardlinkedOutsideClient == false",
			"Label in [\(strings.Join(cats, ","))]",
		]
	},
	{
		name: "not-linked"
		mode: "remove"
		update: ["HardlinkedOutsideClient == true"]
	},

	for t in #trackers {
		name: "site:\(t.name)"
		let match = _#trackerMatchByName[t.name]
		update: [match]
	},

	for t in #trackers
	if (t.tags & [...string]) != _|_ {
		for tag in t.tags {
			name: "\(tag)"
			mode: "add"
			let match = _#trackerMatchByName[t.name]
			update: [match]
		}
	},

	for tag, _ in _#trackerTagSet {
		name: tag
		mode: "remove"
		let keep = [
			for t in #trackers if (t.tags & [...string]) != _|_ {
				let match = _#trackerMatchByName[t.name]
				for trackerTag in t.tags if trackerTag == tag {
					"(\(match))"
				}
			},
		]
		update: ["\(strings.Join(keep, " || "))"]
	},

	for t in #trackers
	if t.minSeedDays != _|_ {
		name: "hnr"
		mode: "add"
		let match = _#trackerMatchByName[t.name]
		update: list.Concat([
			[match],
			["SeedingDays < \(t.minSeedDays)"],
		])
	},
	{
		name: "hnr"
		mode: "remove"
		let keep = [
			for t in #trackers if t.minSeedDays != _|_ {
				let match = _#trackerMatchByName[t.name]
				"(\(match) && SeedingDays < \(t.minSeedDays))"
			},
		]
		update: ["\(strings.Join(keep, " || "))"]
	},
]

filters: default: remove: [
	"IsUnregistered()",
	"HasAllTags(\"not-linked\") && SeedingDays > 14",
	"Downloaded == false && AddedDays > 7",

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

	for t in #trackers if t.minSeedDays != _|_ {
		"HasAllTags(\"site:\(t.name)\", \"not-linked\") && SeedingDays >= \(t.minSeedDays)"
	},
]
