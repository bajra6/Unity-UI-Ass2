using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

// Self-contained procedural meadow: no downloaded art or additional packages.
public class GrasslandEnvironment : MonoBehaviour
{
    readonly List<Object> generated = new List<Object>();
    readonly System.Random random = new System.Random(731);
    Material grass, bark, leaves, lightLeaves, wood;
    Material previousSky, sky;

    float Range(float min, float max) => Mathf.Lerp(min, max, (float)random.NextDouble());

    Material Material(string name, Color color)
    {
        var shader = Shader.Find("Universal Render Pipeline/Lit");
        if (!shader) shader = Shader.Find("Standard");
        var material = new Material(shader) { name = name, color = color };
        material.SetFloat("_Smoothness", 0);
        generated.Add(material);
        return material;
    }

    GameObject Shape(string name, PrimitiveType type, Vector3 position, Vector3 scale, Material material, bool solid = false)
    {
        var obj = GameObject.CreatePrimitive(type);
        obj.name = name;
        obj.transform.SetParent(transform, false);
        obj.transform.localPosition = position;
        obj.transform.localScale = scale;
        obj.GetComponent<Renderer>().sharedMaterial = material;
        if (!solid)
        {
            obj.GetComponent<Collider>().enabled = false;
            Destroy(obj.GetComponent<Collider>());
        }
        return obj;
    }

    public void Build()
    {
        grass = Material("Meadow blades", new Color(.31f, .48f, .12f));
        bark = Material("Tree bark", new Color(.29f, .18f, .09f));
        leaves = Material("Deep foliage", new Color(.20f, .37f, .10f));
        lightLeaves = Material("Sunlit foliage", new Color(.37f, .53f, .15f));
        wood = Material("Weathered fence", new Color(.52f, .39f, .23f));
        var ground = Material("Meadow ground", Color.white);
        var texture = new Texture2D(128, 128, TextureFormat.RGB24, true) { name = "Meadow color variation", wrapMode = TextureWrapMode.Repeat };
        var pixels = new Color[128 * 128];
        for (int y = 0; y < 128; y++)
            for (int x = 0; x < 128; x++)
            {
                float noise = Mathf.PerlinNoise(x / 20f, y / 20f) * .8f + Range(0, .2f);
                pixels[y * 128 + x] = Color.Lerp(new Color(.30f, .43f, .13f), new Color(.47f, .57f, .23f), noise);
            }
        texture.SetPixels(pixels);
        texture.Apply();
        generated.Add(texture);
        ground.mainTexture = texture;
        ground.mainTextureScale = new Vector2(14, 14);
        Shape("Grassland ground", PrimitiveType.Cube, new Vector3(0, -.15f, 0), new Vector3(180, .3f, 180), ground, true);

        BuildGrass();
        BuildFence();
        // Trees stay beyond the fetch clearing, leaving the targets unobstructed.
        for (int i = 0; i < 30; i++)
        {
            float angle = i * Mathf.PI * 2 / 30 + Range(-.08f, .08f);
            float radius = Range(16, 36);
            BuildTree(new Vector3(Mathf.Cos(angle) * radius, 0, Mathf.Sin(angle) * radius), Range(.8f, 1.5f));
        }
        var distant = Material("Distant hills", new Color(.34f, .48f, .28f));
        for (int i = 0; i < 12; i++)
        {
            float angle = i * Mathf.PI * 2 / 12;
            Shape("Rolling hill", PrimitiveType.Sphere, new Vector3(Mathf.Cos(angle) * 65, -3, Mathf.Sin(angle) * 65),
                new Vector3(Range(30, 48), Range(12, 22), Range(24, 38)), distant);
        }

        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(.66f, .78f, .91f);
        RenderSettings.ambientEquatorColor = new Color(.56f, .64f, .43f);
        RenderSettings.ambientGroundColor = new Color(.30f, .36f, .20f);
        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.Linear;
        RenderSettings.fogColor = new Color(.73f, .84f, .89f);
        RenderSettings.fogStartDistance = 45;
        RenderSettings.fogEndDistance = 125;
        previousSky = RenderSettings.skybox;
        var skyShader = Shader.Find("Skybox/Procedural");
        if (skyShader)
        {
            sky = new Material(skyShader) { name = "Meadow sky" };
            sky.SetColor("_SkyTint", new Color(.48f, .60f, .75f));
            sky.SetFloat("_AtmosphereThickness", .8f);
            sky.SetFloat("_SunSize", .035f);
            generated.Add(sky);
            RenderSettings.skybox = sky;
        }
    }

    void BuildTree(Vector3 position, float size)
    {
        Shape("Tree trunk", PrimitiveType.Cylinder, position + Vector3.up * 1.6f * size,
            new Vector3(.45f, 1.6f, .45f) * size, bark, true);
        Shape("Tree canopy", PrimitiveType.Sphere, position + Vector3.up * 4.1f * size,
            new Vector3(3.7f, 3.8f, 3.3f) * size, leaves);
        Shape("Sunlit canopy", PrimitiveType.Sphere, position + new Vector3(.85f, 4.7f, -.25f) * size,
            new Vector3(2.7f, 2.8f, 2.6f) * size, lightLeaves);
        Shape("Side canopy", PrimitiveType.Sphere, position + new Vector3(-1.1f, 3.7f, .4f) * size,
            new Vector3(2.4f, 2.5f, 2.5f) * size, leaves);
    }

    void BuildFence()
    {
        for (int side = 0; side < 4; side++)
        {
            var rotation = Quaternion.Euler(0, side * 90, 0);
            for (int i = 0; i <= 8; i++)
                Shape("Fence post", PrimitiveType.Cube, rotation * new Vector3(-11 + i * 2.75f, .53f, 11),
                    new Vector3(.14f, 1.06f, .14f), wood, true);
            foreach (float height in new[] { .38f, .78f })
            {
                var rail = Shape("Fence rail", PrimitiveType.Cube, rotation * new Vector3(0, height, 11),
                    new Vector3(22, .12f, .10f), wood, true);
                rail.transform.localRotation = rotation;
            }
        }
    }

    void BuildGrass()
    {
        // One combined mesh instead of thousands of objects. Low blades keep the red ball visible.
        var vertices = new List<Vector3>();
        var triangles = new List<int>();
        for (int tuft = 0; tuft < 6000; tuft++)
        {
            Vector3 root = new Vector3(Range(-38, 38), .008f, Range(-38, 38));
            bool clearing = Mathf.Abs(root.x) < 11 && Mathf.Abs(root.z) < 11;
            float height = clearing ? Range(.06f, .15f) : Range(.20f, .55f);
            for (int blade = 0; blade < 3; blade++)
            {
                float angle = Range(0, Mathf.PI * 2);
                Vector3 width = new Vector3(Mathf.Cos(angle), 0, Mathf.Sin(angle)) * height * .16f;
                int start = vertices.Count;
                vertices.Add(root - width);
                vertices.Add(root + width);
                vertices.Add(root + Vector3.up * height + width * Range(-1.5f, 1.5f));
                triangles.AddRange(new[] { start, start + 2, start + 1, start, start + 1, start + 2 });
            }
        }
        var mesh = new Mesh { name = "Combined meadow grass" };
        mesh.SetVertices(vertices);
        mesh.SetTriangles(triangles, 0);
        // Upward normals give both sides soft meadow lighting; opposite triangle
        // windings would cancel out if normals were averaged automatically.
        var normals = new Vector3[vertices.Count];
        for (int i = 0; i < normals.Length; i++) normals[i] = Vector3.up;
        mesh.normals = normals;
        mesh.RecalculateBounds();
        generated.Add(mesh);
        var obj = new GameObject("Grass tufts");
        obj.transform.SetParent(transform, false);
        obj.AddComponent<MeshFilter>().sharedMesh = mesh;
        var renderer = obj.AddComponent<MeshRenderer>();
        renderer.sharedMaterial = grass;
        renderer.shadowCastingMode = ShadowCastingMode.Off;
    }

    void OnDestroy()
    {
        if (RenderSettings.skybox == sky) RenderSettings.skybox = previousSky;
        foreach (var asset in generated) if (asset) Destroy(asset);
    }
}
