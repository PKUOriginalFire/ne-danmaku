export const GiftType = {
    GOOD: "good",
    FLOWER: "flower",
    COW: "cow",
    TOWER: "tower",
    LAKE: "lake",
    LIBRARY: "library",
    EGG: "egg",
    LYCORIS: "lycoris",
    SHIP: "ship",
    MOM: "mom",
    DASH: "dash",
    NANYIMI: "nanyimi",
    HACHIMI: "hachimi",
    ORIGINALFIRE: "originalFire",
    BLUESHIT: "blueShit",
    EGGPLANT: "eggplant",
} as const

export type GiftType = typeof GiftType[keyof typeof GiftType]

export const GiftConfig: Record<GiftType, {
    name: string;
    imageUrl: string;
    cost: number;
    level: number; // 优先级
}> = {
    good: {
        name: "这个好诶",
        imageUrl: "/assets/gifts/good.png",
        cost: 1,
        level: 1,
    },
    flower: {
        name: "小花花",
        imageUrl: "/assets/gifts/flower.png",
        cost: 1,
        level: 1,
    },
    cow: {
        name: "牛哇牛哇",
        imageUrl: "/assets/gifts/cow.png",
        cost: 1,
        level: 1,
    },
    tower: {
        name: "博雅塔",
        imageUrl: "/assets/gifts/tower.png",
        cost: 5,
        level: 2,
    },
    lake: {
        name: "未名湖",
        imageUrl: "/assets/gifts/lake.png",
        cost: 5,
        level: 2,
    },
    library: {
        name: "图书馆",
        imageUrl: "/assets/gifts/library.png",
        cost: 5,
        level: 2,
    },
    egg: {
        name: "蛋",
        imageUrl: "/assets/gifts/egg.png",
        cost: 10,
        level: 3,
    },
    lycoris: {
        name: "蒜",
        imageUrl: "/assets/gifts/lycoris.png",
        cost: 10,
        level: 3,
    },
    ship: {
        name: "大航海",
        imageUrl: "/assets/gifts/ship.png",
        cost: 10,
        level: 3,
    },
    mom: {
        name: "妈咪",
        imageUrl: "/assets/gifts/mom.png",
        cost: 20,
        level: 4,
    },
    dash: {
        name: "♿冲刺♿",
        imageUrl: "/assets/gifts/dash.png",
        cost: 20,
        level: 4,
    },
    nanyimi: {
        name: "何意味",
        imageUrl: "/assets/gifts/nanyimi.png",
        cost: 20,
        level: 4,
    },
    hachimi: {
        name: "蜂蜜特饮",
        imageUrl: "/assets/gifts/hachimi.png",
        cost: 20,
        level: 4,
    },
    originalFire: {
        name: "元火",
        imageUrl: "/assets/gifts/originalFire.png",
        cost: 50,
        level: 5,
    },
    blueShit: {
        name: "挖掘机",
        imageUrl: "/assets/gifts/blueShit.png",
        cost: 50,
        level: 5,
    },
    eggplant: {
        name: "谢谢茄子",
        imageUrl: "/assets/gifts/eggplant.png",
        cost: 50,
        level: 5,
    },
}

const giftNames = Object.values(GiftConfig).map(g => g.name)

export function isGiftType(value: string): value is GiftType {
    return (
        value in GiftConfig ||
        giftNames.includes(value)
    )
}

export function formGiftType(value: string): GiftType {
    if (value in GiftConfig) {
        return value as GiftType
    }

    const entry = Object.entries(GiftConfig).find(
        ([_, config]) => config.name === value
    )

    if (entry) {
        return entry[0] as GiftType
    }

    throw new Error(`Unknown gift type: ${value}`)
}