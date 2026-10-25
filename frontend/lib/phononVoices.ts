// English voices from the gradium/phonon-voices catalog (voices.jsonl), which is
// Apache-2.0. phonon-31m-en is English-only, so the French/German/Spanish/
// Portuguese voices are left out. Generated once from that file -- add a voice by
// copying its row (id = voice_id; the file is voices/<id>.safetensors).
// Pinned to a commit so the browser's cached copies never go stale.
export const VOICES_REVISION = "0ee17205f254b5abc43b266c8a0f215565c352f7";

export type PhononVoice = {
  id: string;
  name: string;
  group: "US" | "UK" | "Character";
  gender: "female" | "male" | null;
  description: string;
};

export function voiceUrl(voice: PhononVoice): string {
  return `https://huggingface.co/gradium/phonon-voices/resolve/${VOICES_REVISION}/voices/${voice.id}.safetensors`;
}

export const PHONON_VOICES: PhononVoice[] = [
  { id: "nGzMHMPAWGaJFHOo", name: "Delia", group: "US", gender: "female", description: "Low, grounded and quick to the point, with a sincerity that keeps an apology honest." },
  { id: "vjFyp2BcCyTlUmYb", name: "Everly", group: "US", gender: "female", description: "Rounded, soft-edged tone with gentle lift at the end of phrases and an easy, relaxed delivery." },
  { id: "bXwrkHhURL1VFJdG", name: "Hadley", group: "US", gender: "female", description: "Settled, even-toned and genuinely kind, with crisp consonants that hold up over a handset." },
  { id: "4SZHfMpw-p46Ywgs", name: "Harper", group: "US", gender: "female", description: "Modern, confident and friendly voice with a standard American accent." },
  { id: "NIWIOv5vTi5eRMj8", name: "Juniper", group: "US", gender: "female", description: "Cheerful presence with real resonance under it, personable when the copy turns intimate and decisive on the final line." },
  { id: "NbpkqMVS3CJeq2j8", name: "Zoey", group: "US", gender: "female", description: "Playful, upbeat and Gen Z energy voice with a standard American accent. Perfect for engaging conversations!" },
  { id: "LMDIYE0Oa377Qh6Z", name: "Easton", group: "US", gender: "male", description: "Punchy and close in, with crisp consonant attack that cuts through a music bed and pitch that lifts across each line." },
  { id: "40QrMVgAxFiUnP9f", name: "Micah", group: "US", gender: "male", description: "Buoyant and high in energy, with a playful lift at the ends of phrases and clean attack that survives a loud mix." },
  { id: "d9XCyhjo4JhkHF1d", name: "Miles", group: "US", gender: "male", description: "Resonant and decisive, with genuine dynamic range, dropping right down for one clause then driving back up." },
  { id: "qIxlZ7Ei8KvWlyQH", name: "Preston", group: "US", gender: "male", description: "Trim, focused delivery with clean edges on every consonant and a steady, low-set core that carries through phone bandwidth." },
  { id: "_6Aslh2DxfmnRLmP", name: "Russell", group: "US", gender: "male", description: "A high-energy American adult voice that pushes and encourages with the intensity of someone who genuinely believes in you." },
  { id: "0zLApsZfVLLNaEGl", name: "Trevor", group: "US", gender: "male", description: "Buoyant energy over a resonant mid-low core, phrases landing softly and consonants cutting through a handset." },
  { id: "gfP44RlHwr2kEwk7", name: "Bryony", group: "UK", gender: "female", description: "Full, rich mid-range tones, softly relaxed and spoken close to the mic, moving briskly with light pitch play." },
  { id: "y9bQqIDnyxwqK01t", name: "Elodie-Rose", group: "UK", gender: "female", description: "A young British voice with sharp, enthusiastic energy and crisp articulation, sparky and to the point for customer support and care." },
  { id: "GgfEkEJtxZR7gnpy", name: "Freya", group: "UK", gender: "female", description: "A young British voice, glossy and confident with fast, girly chatter and bubbly sparkle, perfect for a friendly receptionist or assistant." },
  { id: "gDT1nz7Ie36ZhL-C", name: "Imogen", group: "UK", gender: "female", description: "A bubbly, friendly British English adult voice that puts callers instantly at ease. Great for onboarding assistants and warm concierge interactions." },
  { id: "m9MxpY6IUGXtWp76", name: "Lottie", group: "UK", gender: "female", description: "Sparky and to the point, high forward energy with clean edges on the consonants and the range to drop low for one line then climb back." },
  { id: "6PWnV0Nq4wu7RVBT", name: "Maeve", group: "UK", gender: "female", description: "A sparky, attentive British English adult voice that gets to the point with a smile. Ideal for fast, efficient customer support and helpful voice assistants." },
  { id: "uem82D50GRv2Dwma", name: "Pippa", group: "UK", gender: "female", description: "A confident, upbeat British English adult voice with infectious energy. Perfect for proactive assistants and motivating customer success calls." },
  { id: "X6NceqF285Gr04gb", name: "Alfie", group: "UK", gender: "male", description: "Punchy and forward, with crisp consonant attack and a pitch that lifts across a line, sitting high over a music bed." },
  { id: "zUCxzrOrugTSis03", name: "Edwin", group: "UK", gender: "male", description: "Efficient and firm, sincere in attention, with tidy articulation that holds up at phone bandwidth." },
  { id: "YyKcxPG7iIgS3jsK", name: "Hugh", group: "UK", gender: "male", description: "Soft and close, airy in texture, with lively pitch movement and an attentive, sincere delivery." },
  { id: "JOW0vchyswkQUMDS", name: "Spencer", group: "UK", gender: "male", description: "Light and airy, sitting a touch higher, with crisp consonants and a slow, patient delivery." },
  { id: "Zn7g6NxLqXlJb7Qi", name: "Teddy", group: "UK", gender: "male", description: "Sparky and close in, quick off the mark, with firm consonants and the range to drop right down for a clause then come back up." },
  { id: "dME3IWyZBvmh1n1q", name: "Toby", group: "UK", gender: "male", description: "A sparky, attentive British English adult voice that gets to the point with a smile. Ideal for fast, efficient customer support and helpful voice assistants." },
  { id: "dGyGDKo2osj7h3s7", name: "Azgorath", group: "Character", gender: null, description: "An enormous ancient demon. A cavernous, impossibly deep bass voice that rumbles like stone grinding in a crypt, with a dry rasping edge and a faint hiss on every s. Calm, slow and amused, never shouting, every syllable set down deliberately, menace held under perfect control." },
  { id: "xPDpsV3F592srkjA", name: "Captain Silas Blackwater", group: "Character", gender: null, description: "An old British pirate captain from the West Country, around sixty. Deep, gravelly and booming, rolling his Rs, salt-cracked from decades of shouting over gales. Roguish and hearty, with a wicked chuckle under every boast." },
  { id: "QXNr0SvkukLB4wPq", name: "Fairy Godmother", group: "Character", gender: null, description: "A kind fairy godmother, an older woman in her sixties. A low, warm, velvety alto voice, cosy and grandmotherly, unhurried and soothing, with a soft rich chuckle and a twinkle in every word. Gentle and reassuring, never high, never thin." },
  { id: "cXoIXJ2llS8S0WOW", name: "Fennick the Young Elf", group: "Character", gender: null, description: "A curious, kind-hearted elf boy of about ten. A natural child's voice in a warm, soft middle range, never squeaky or shrill, earnest and wide-eyed, a little breathless with excitement, speaking quickly when amazed. Clean, close studio recording with no background noise or hiss." },
  { id: "cYtsRSxV5q9IMehn", name: "Grub the Ogre", group: "Character", gender: null, description: "A big, good-natured ogre who lives under a bridge. Gruff and grainy, rumbling low end, heavy chest resonance, slow lumbering rhythm with loose rounded words, and warm humour sitting just under the grumble." },
  { id: "gSgG5Tor0GPEnqzC", name: "Master Aldric", group: "Character", gender: null, description: "A wise old British wizard, around eighty. Rich and resonant with an aged grain, warm and kindly, deliberate pace with weighted pauses before the words that matter, able to rise into a ringing incantation." },
  { id: "nOykTmcH9ydsGGIc", name: "Morwenna of the Deep", group: "Character", gender: null, description: "A sultry, seductive woman in her thirties. Low, husky alto, close to the microphone and almost whispered, slow and languid, purring, with a warm knowing smile in every word. Intimate, flirtatious and teasing, like a late-night torch singer luring someone closer, with a hint of danger underneath." },
  { id: "lX3LavMNdlIbgEHH", name: "Old Mortlake", group: "Character", gender: null, description: "An elderly gravedigger in a Victorian churchyard. Low, raspy and half whispered, melancholic, with heavy pauses that let every word settle like dirt on a coffin lid." },
  { id: "y2eiKxtQo2B67deU", name: "Sir Bramwell", group: "Character", gender: null, description: "A brave but pompous English knight, middle-aged. Booming, plummy and theatrical, full of puffed-up self-importance, rolling grand phrases, with a comic wobble of nerves showing through the bravado." },
  { id: "NIWoEurJHMJjyUTe", name: "The Snow Queen", group: "Character", gender: null, description: "A regal, cold-hearted queen of ice. A cool, crystalline mezzo voice, poised and elegant, precise articulation, unhurried and quietly commanding, with an enigmatic chill and a faint smile that never warms." },
  { id: "GXaSqMEmOg12OIYb", name: "The Thing Under the Stairs", group: "Character", gender: null, description: "A monstrous creature lurking in the dark. Gravelly, breathy and pitched near the floor, a threatening growl that stays quiet to stay frightening, with a slow mocking sneer." },
  { id: "xO8xQo3BrB8FuI6J", name: "Vyrmathrax the Ancient", group: "Character", gender: null, description: "An ancient dragon, thousands of years old. Very low and resonant, deep chest weight with gravel at the bottom of the register, slow and controlled with long pauses, dry and offhand, with the flat calm of something far too old to be impressed." },
];
