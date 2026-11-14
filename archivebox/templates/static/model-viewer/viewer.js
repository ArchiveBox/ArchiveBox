import {ACESFilmicToneMapping, Box3, Color, DirectionalLight, Group, HemisphereLight, LoadingManager, Mesh, MeshStandardMaterial, PerspectiveCamera, Scene, Vector3, WebGLRenderer, OrbitControls, STLLoader, GLTFLoader, OBJLoader, PLYLoader, ThreeMFLoader} from './three.bundle.js';

const canvas = document.getElementById('model');
const status = document.getElementById('status');
const format = document.body.dataset.modelFormat;
const source = new URL(document.body.dataset.modelUrl, location.href);
const directory = new URL('./', source);
const manager = new LoadingManager();
manager.setURLModifier((url) => {
  if (url.startsWith('data:') || url.startsWith('blob:')) return url;
  const saved = new URL(url, directory);
  if (saved.origin !== source.origin || !saved.pathname.startsWith(directory.pathname)) {
    throw new Error('Model references an asset outside its saved directory');
  }
  saved.searchParams.delete('preview');
  saved.searchParams.set('raw', '1');
  return saved.href;
});

try {
  const renderer = new WebGLRenderer({canvas, antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = ACESFilmicToneMapping;
  const scene = new Scene();
  scene.background = new Color('#f4f6f8');
  scene.add(new HemisphereLight(0xffffff, 0x58657a, 2.8));
  const key = new DirectionalLight(0xffffff, 3.2);
  key.position.set(3, 5, 4);
  scene.add(key);
  const fill = new DirectionalLight(0xffffff, 1.2);
  fill.position.set(-3, 1, -2);
  scene.add(fill);
  const camera = new PerspectiveCamera(40, 1, 0.01, 1000);
  const controls = new OrbitControls(camera, canvas);
  controls.screenSpacePanning = true;
  const render = () => {
    renderer.render(scene, camera);
    canvas.dataset.renderedTriangles = String(renderer.info.render.triangles);
  };
  let fittedAspect = 1;
  let fitDistance = () => 1;
  controls.addEventListener('change', render);
  const resize = () => {
    const {width, height} = canvas.parentElement.getBoundingClientRect();
    renderer.setSize(width, height, false);
    const nextAspect = width / height;
    // Preserve orbit and zoom while keeping the same framing across orientations.
    camera.position.sub(controls.target).multiplyScalar(fitDistance(nextAspect) / fitDistance(fittedAspect)).add(controls.target);
    camera.aspect = fittedAspect = nextAspect;
    camera.updateProjectionMatrix();
    render();
  };
  new ResizeObserver(resize).observe(canvas.parentElement);

  const material = new MeshStandardMaterial({color: 0xa51b55, metalness: 0.12, roughness: 0.65});
  let model;
  if (format === 'stl') model = new Mesh(await new STLLoader(manager).loadAsync(source.href), material);
  else if (format === 'ply') {
    const geometry = await new PLYLoader(manager).loadAsync(source.href);
    geometry.computeVertexNormals();
    if (geometry.hasAttribute('color')) material.vertexColors = true;
    model = new Mesh(geometry, material);
  } else if (format === 'obj') model = await new OBJLoader(manager).loadAsync(source.href);
  else if (format === '3mf') model = await new ThreeMFLoader(manager).loadAsync(source.href);
  else if (format === 'glb' || format === 'gltf') model = (await new GLTFLoader(manager).loadAsync(source.href)).scene;
  else throw new Error('Unsupported model format');

  if (format === 'stl' || format === '3mf') model.rotation.x = -Math.PI / 2;
  const holder = new Group();
  holder.add(model);
  const bounds = new Box3().setFromObject(holder);
  if (bounds.isEmpty()) throw new Error('Model contains no geometry');
  const size = bounds.getSize(new Vector3());
  const center = bounds.getCenter(new Vector3());
  model.position.sub(center);
  scene.add(holder);
  let triangles = 0;
  let meshes = 0;
  holder.traverse(object => {
    if (!object.isMesh) return;
    meshes++;
    triangles += (object.geometry.index?.count || object.geometry.attributes.position.count) / 3;
  });
  if (!meshes) throw new Error('Model contains no meshes');
  const radius = size.length() / 2;
  if (!(radius > 0 && Number.isFinite(radius))) throw new Error('Model contains no bounded geometry');
  const direction = new Vector3(1, 0.65, 1).normalize();
  const right = new Vector3(direction.z, 0, -direction.x).normalize();
  const up = new Vector3().crossVectors(direction, right);
  fitDistance = aspect => {
    const vertical = Math.tan(camera.fov * Math.PI / 360);
    let distance = 0;
    for (const x of [-1, 1]) for (const y of [-1, 1]) for (const z of [-1, 1]) {
      const corner = new Vector3(x * size.x / 2, y * size.y / 2, z * size.z / 2);
      distance = Math.max(distance, corner.dot(direction) + Math.max(Math.abs(corner.dot(right)) / (vertical * aspect), Math.abs(corner.dot(up)) / vertical));
    }
    return distance * 1.1;
  };
  const reset = () => {
    camera.position.copy(direction).multiplyScalar(fitDistance(camera.aspect));
    camera.near = Math.max(radius / 1000, 0.00001);
    camera.far = radius * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.minDistance = radius * 0.05;
    controls.maxDistance = radius * 30;
    controls.update();
    render();
  };
  resize();
  reset();
  document.getElementById('reset').addEventListener('click', reset);
  document.getElementById('wireframe').addEventListener('click', event => {
    const enabled = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    event.currentTarget.setAttribute('aria-pressed', String(enabled));
    holder.traverse(object => {
      if (object.isMesh) for (const item of Array.isArray(object.material) ? object.material : [object.material]) item.wireframe = enabled;
    });
    render();
  });
  document.getElementById('model-info').textContent = `${format.toUpperCase()} · ${Math.round(triangles).toLocaleString()} triangles`;
  canvas.dataset.triangles = String(Math.round(triangles));
  canvas.dataset.meshes = String(meshes);
  canvas.dataset.state = 'ready';
  status.hidden = true;
} catch (error) {
  canvas.dataset.state = 'error';
  status.setAttribute('role', 'alert');
  status.textContent = `Unable to render model: ${error.message}`;
}
