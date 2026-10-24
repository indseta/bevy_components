# Lighting

## Lights

glTF already carries a light's color, power, spot cone and Custom Distance range. Add a **Light** component (under Lighting) to a light for the rest:

- shadows from the light's own **Shadow** checkbox, plus contact shadows, depth and normal bias, and for sun lights the shadow cascades
- **Volumetric** for light shafts through Fog Volumes, and **Baked** to bake the light into lightmaps, so it only adds reflections on lightmapped meshes
- an **Intensity** in Bevy's lumens or lux, in place of Blender's watts at 683 lm/W

Area lights become Bevy `RectLight`s, which need Bevy's `area_light_luts` feature and cast no shadows. Contact shadows need `ContactShadows` and a depth prepass on the camera. The viewport draws how far each light reaches, 20 m unless Custom Distance is on, and dragging its arrow sets Custom Distance.

## Ambient light and sky

**Properties > World > Bevy Ambient Light** sets the scene's ambient light, from the World color or a color and brightness of its own.

**Properties > World > Bevy Sky** shows the World behind every `Camera3d` as a `Skybox`, from a cubemap that its **Bake** button renders of the World alone. With **Environment Light** on, the sky also lights the scene through a `GeneratedEnvironmentMapLight`, which adds reflections everywhere and soft light where no lightmap or irradiance volume reaches. The export then sets Bevy's ambient light to 0 unless Bevy Ambient Light is on, so the sky does not light the scene twice. Add `NoBlenderSky` to a camera to leave it out, or read the `BlenderSky` resource to set up cameras yourself.

## Fog and light probes

**Fog Volume**, **Reflection Probe** and **Irradiance Volume** (under Lighting) are boxes. Set their size on Bevy's axes or drag the arrows in the viewport, where the inner box of a probe shows where its falloff starts.

- **Fog Volume** fills its box with volumetric fog. Bevy only draws it for cameras with `VolumetricFog`, such as `commands.spawn((Camera3d::default(), VolumetricFog::default()))`, and once a light in the scene has **Volumetric** on in its Light component.
- **Reflection Probe** gives the meshes in its box reflections and soft light from a cubemap. Bevy filters the cubemap when the scene loads, so it needs six square faces whose size is a power of two, and no mipmaps. **Bake** makes one (see [Baked lighting](#baked-lighting)), or KTX-Software from six renders: `ktx create --format R16G16B16A16_SFLOAT --cubemap px.exr nx.exr py.exr ny.exr pz.exr nz.exr room.ktx2`.
- **Irradiance Volume** lights the meshes in its box from a grid of light samples. Its file is a 3D texture in Bevy's layout, where X × Y × Z samples take X × 2Y × 3Z texels, and **Bake** makes one.

The export embeds each probe's `.ktx2` file in the GLB, so the scene stays one file and needs no extra loading code. Save them uncompressed, such as RGBA16F. Bevy cannot use Basis Universal here, and block-compressed formats only load on GPUs that support them.

## Baked lighting

The addon bakes lightmaps, Reflection Probes, Irradiance Volumes and the Bevy Sky with Cycles.

1. Add a **Lightmap** (under Lighting) to each static mesh and click **Unwrap Lightmap UVs**, which fills the mesh's second UV map, the one Bevy reads lightmaps with. For a probe, size its box and set its **Bake Size** (pixels per cubemap face) or **Bake Voxels** (light samples along X, Y and Z).
2. Click **Bake** on a component to bake just that one, or pick **Bake Lighting...** in the components dropdown to bake everything in the scene. The dialog sets the Cycles samples and the folder, `//baked_lighting/` next to the `.blend` file by default, and **Export Again** exports the scene to the GLB or BSN file of its last export once the bake finishes.

A second Blender bakes a copy of the scene in the background, so you can keep working. The status bar shows the progress and its **X** cancels; bakes that already finished keep their new files. Each component's file is set to its result, and the export embeds it like any other. Bakes started from a script finish before the call returns.

Each bake remembers the scene it rendered: for a probe the meshes in its box, for a lightmap its mesh and the meshes touching it, with their materials, plus the lamps and the World. When one of those changes, the export checks warn that the bake is out of date.

- A lightmap holds the light from the sky and emissive materials and the light that bounces between surfaces. Bevy lights the mesh with the exported lamps as usual, except lamps whose Light component is **Baked**: their direct light and shadows go into the lightmap, and Bevy only adds their reflections.
- Turn on **Bevy Ambient Light** and its **Baked** option in the World properties, so Bevy keeps its ambient light off lightmapped meshes.
- Lightmaps are 4 bytes per pixel, so a 512 px lightmap adds 1 MB to the exported scene. Unwrap again after changing a lightmap's **Bake Size**, so its UV islands stay a few pixels apart. Keep modifiers the same in the viewport and in renders: the bake renders the ones enabled for renders, and the export applies the ones shown in the viewport while **Apply Modifiers** is on.
- Lightmapped meshes skip irradiance volumes, which light the moving objects instead. Irradiance volumes leave out the light lamps shine straight at them, since Bevy lights meshes with the exported lamps itself. Turn on **Direct Lamp Light** for lamps you do not export.
- Bevy adds its ambient light on top of irradiance volumes, so turn off **Bevy Ambient Light** when volumes cover the scene and nothing is lightmapped, or the sky lights it twice.
- A probe's **Intensity** starts at 683, which converts Blender's light units the way the glTF export converts lamps, so baked light matches them. Lightmaps are stored at that scale already.
- Let each box reach a little past the floors and walls it should light, since Bevy skips surfaces right on its edge. A Reflection Probe renders its cubemap from the center of its box, so keep that spot clear of meshes.
- The bake uses your Cycles settings, such as the device and light bounces, and skips objects that are disabled in renders. Only reflection probes are denoised, so raise the samples if a lightmap looks grainy.
