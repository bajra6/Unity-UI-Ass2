using System.IO;
using UnityEditor;
using UnityEngine;

public static class GoodBoyArt
{
    [MenuItem("Good Boy/Rebuild Character Prefabs")]
    public static void Build()
    {
        Directory.CreateDirectory("Assets/GoodBoy/Resources/Characters");
        BuildOne("Assets/GoodBoy/Art/Dog.fbx", "Dog", .95f);
        BuildOne("Assets/GoodBoy/Art/Person/Owner.obj", "Owner", 1.85f);
        AssetDatabase.SaveAssets();
        Debug.Log("GOODBOY_ART_OK");
    }

    static void BuildOne(string path, string name, float height)
    {
        var importer=AssetImporter.GetAtPath(path) as ModelImporter;
        importer.isReadable=true;
        importer.materialImportMode=ModelImporterMaterialImportMode.ImportStandard;
        importer.SaveAndReimport();
        var source=AssetDatabase.LoadAssetAtPath<GameObject>(path);
        var root=new GameObject(name);
        var model=Object.Instantiate(source,root.transform);
        model.name=name+" mesh";
        var renderers=model.GetComponentsInChildren<Renderer>();
        var bounds=renderers[0].bounds;
        foreach(var r in renderers) bounds.Encapsulate(r.bounds);
        if(name=="Dog")
        {
            Transform nose=null;
            foreach(var t in model.GetComponentsInChildren<Transform>()) if(t.name=="Nose") nose=t;
            if(nose)
            {
                Vector3 forward=nose.position-bounds.center;forward.y=0;
                model.transform.rotation=Quaternion.FromToRotation(forward.normalized,Vector3.forward);
            }
        }
        bounds=renderers[0].bounds;
        foreach(var r in renderers)bounds.Encapsulate(r.bounds);
        model.transform.localScale*=height/bounds.size.y;
        bounds=renderers[0].bounds;
        foreach(var r in renderers)bounds.Encapsulate(r.bounds);
        model.transform.position-=new Vector3(bounds.center.x,bounds.min.y,bounds.center.z);
        var converted=new System.Collections.Generic.Dictionary<Material,Material>();
        foreach(var r in renderers)
        {
            var materials=r.sharedMaterials;
            for(int i=0;i<materials.Length;i++)
            {
                var original=materials[i];
                if(!converted.TryGetValue(original,out var material))
                {
                    material=new Material(Shader.Find("Universal Render Pipeline/Lit"));
                    material.name=name+" "+original.name;
                    Color color=original.HasProperty("_Color") ? original.color:Color.white;
                    Texture texture=original.mainTexture;
                    if(name=="Owner" && original.name.Contains("material_7"))
                    { color=new Color(.035f,.23f,.68f);texture=null; }
                    material.SetColor("_BaseColor",color);
                    material.SetColor("_Color",color);
                    material.SetTexture("_BaseMap",texture);
                    material.SetFloat("_Smoothness",name=="Dog" ? .22f:.16f);
                    material.SetFloat("_Metallic",0);
                    material.SetFloat("_Cull",0);
                    if(name=="Owner" && (original.name.Contains("material_2") || original.name.Contains("material_3") || original.name.Contains("material_4") || original.name.Contains("material_10")))
                    {
                        material.SetFloat("_AlphaClip",1);material.SetFloat("_Cutoff",.45f);
                        material.EnableKeyword("_ALPHATEST_ON");material.renderQueue=2450;
                    }
                    string asset=$"Assets/GoodBoy/Resources/Characters/{name}_{converted.Count}.mat";
                    var existing=AssetDatabase.LoadAssetAtPath<Material>(asset);
                    if(existing) { EditorUtility.CopySerialized(material,existing); Object.DestroyImmediate(material);material=existing; }
                    else AssetDatabase.CreateAsset(material,asset);
                    converted[original]=material;
                }
                materials[i]=material;
            }
            r.sharedMaterials=materials;
        }
        PrefabUtility.SaveAsPrefabAsset(root,$"Assets/GoodBoy/Resources/Characters/{name}.prefab");
        Object.DestroyImmediate(root);
    }
}
