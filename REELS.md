# Reels

Reels are short play-throughs derived from saved simulations. The goal is to provide an engaging video of a portion of the simulation designed for students to practice a foreign language. We'll stick with English for now. Down the road we'll build simulations that offer easier language material and different languages (or translate the reels to different languages).

A reel follows a single persona as they walk around in the simulation. It layers on an internal monologue that is generated from an LLM post-hoc based on the actions taken by the persona in the simulation and their reflections and memories. Reels offers a Phaser based game server that lets the game play be visualized, using the same assets as the main game, but oriented towards providing a compelling visual experience for a language learner. 

## Character movement

The reel follows a character as they walk around the map, panning to new areas of the map as the character moves. As the main persona walks too near the edge (a configurable distance), the view pans to a part of the map computed to show the persona near the center of the view (at least as much as possible given the constraints of the map itself--the view doesn't move off the edge of the map).

## Time control

The reel doesn't advance at the original simulations time clock. Instead the replay clock is matched to the requirements of the speech that exists in the reel, including the inner monologues and conversations. A conversation can take a substantial amount of time to play through, and parts of the game that have inner monologue will also be slower and parts where the character is just walking from one place to another can be faster. Once the inner monologue and conversations are prepared, they are converted into speech using TTS. At this point time stamps are available. These are then mapped onto the time stamps in the game. The game animation is then paused or stretched where necessary, or sped up or elided so that the reel has a natural flow.

It's possible to generate a reel without speech by assuming a fixed characters/min speaking rate and just showing the text.

## Conversations

In the simulation, conversations are generated in one fell swoop, I believe. In the reels they play out line by line like actual people talking to each other. This is visualized by a chat style interface on the right side of the map that shows the conversation unfold line by line. The text of the conversation appears like someone typing, matched to the word-level timestamps of the audio (this can be acquired using OpenAI's whisper model with timestamp information). Each character's text block is prefixed by their persona sprite and initials so the student can see who is speaking.

## Inner monologues

The inner monologue is generated using prompts that combine a monologue prompt, the information about the speaking persona, and the relevant actions, places, memories, and reflections from that part of the simulation.

The inner monologue is shown like a conversation, with just one participant. It can also be shown just as text at a fixed speaking rate or using text-to-speech.

## Text to speech

Text-to-speech from Inworld is used to generate the speech to go with the inner monologues. Text-to-speech incurs API costs, so the reel is developed and tested assuming a fixed rate of speech and audio is only added towards the end when we're satisfied with the text and timing and reel configuration.

## Configuring a reel

A reel can be configured to focus on certain parts of a persona's experience based on the memory node numbers. Although a reel follows a particular persona throughout that part of the day, all the other personas of the simulation are also present and doing what they do in the simulation at each corresponding time step.

## Reel CLI

The reel.py script is a CLI that handles various tasks associated with reel generation. It handles extracting and repackaging the the simulation history into a format that preserves and re-organizes the information required to make the reel.

Here are some things the CLI should be able to do:

1. Prepare the data structure of data extracted from the simulation history.
2. Generate prompts loaded with context for generating the inner monologue and store it in the data structure. This can be refined and customized with human input.
3. Generate the inner monologues using a configured GPT model.
4. Generate the interpolated time sequence.
5. Use inworld to generate the TTS audio for the inner monologue and conversations (voices are part of the reel configuration).
6. Execute replay of the simulation for recording using screen capture in the browser, with audio playing timed to the conversations.

## Questions

1. Should the reel CLI take the compressed history or the uncompressed history?
2. What information is needed for the reel data structure and what format should it have?

## Suggestions

1. The CLI should be designed to have features and data structures that make it easy for agents to check their work, validate correctness and get insight into the quality of the reels.
2. It should be easy to view the selected memories and other information prepared for generating inner monologues so it's clear what context the prompt for writing the inner monologues
3. It might work best to generate separate inner monologues and put them together
4. The reel doesn't need to capture the whole game, just sections
5. Perhaps different sections of the reel can be spliced together with a fade out fade in transition or something.
6. Prompts used for reel generation should exist as a library of files and the prompts that are used for generating any particular reel can be configured and different versions can be tried.
7. It should be possible to test each different part of reel development individually so steps can be examined, tested and fixed.