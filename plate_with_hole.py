#!/usr/bin/env python3
# ---------------------------------------------------------------
#  Stress Concentration in a Plate with a Central Hole – 2-D FEM
#  • plain-NumPy implementation of Q4 isoparametric elements
#  • structured mesh with internal hole
#  • plane-stress linear elasticity
#  • post-processing: displacements, full stress tensor, von-Mises
# ---------------------------------------------------------------
import numpy as np
import matplotlib.pyplot as plt

# ----------------------------------------------------------------
# 1. Material model (linear–elastic isotropic, plane stress)
# ----------------------------------------------------------------
class Material:
    """Linear elastic, isotropic, plane-stress constitutive matrix"""
    def __init__(self, E: float, nu: float):
        self.E, self.nu = E, nu
        fac = E / (1.0 - nu ** 2)
        self.D = fac * np.array([[1,   nu,          0],
                                 [nu,  1,           0],
                                 [0,   0, (1 - nu) / 2]])

# ----------------------------------------------------------------
# 2. Q4 element definition
# ----------------------------------------------------------------
class Q4Element:
    gp  = (-1/np.sqrt(3),  1/np.sqrt(3))           # Gauss abscissas
    w   = (1.0, 1.0)                               # weights

    def __init__(self, node_ids, coords, mat: Material, t=1.0):
        self.nid  = node_ids       # 4 global node numbers
        self.xy   = coords         # 4×2 array of nodal coordinates
        self.D    = mat.D
        self.t    = t              # thickness

    # shape functions and natural derivatives --------------------
    @staticmethod
    def N(xi, eta):
        return 0.25 * np.array([(1 - xi) * (1 - eta),
                                (1 + xi) * (1 - eta),
                                (1 + xi) * (1 + eta),
                                (1 - xi) * (1 + eta)])

    @staticmethod
    def dN_dxi(xi, eta):
        return 0.25 * np.array([[-(1 - eta), -(1 - xi)],
                                [ (1 - eta), -(1 + xi)],
                                [ (1 + eta),  (1 + xi)],
                                [-(1 + eta),  (1 - xi)]])

    # strain–displacement matrix B and |J| ------------------------
    def _Bmatrix(self, xi, eta):
        dN_nat  = self.dN_dxi(xi, eta)             # 4×2 (dN/dxi, dN/deta)
        J       = dN_nat.T @ self.xy               # 2×2 Jacobian
        detJ    = np.linalg.det(J)
        if abs(detJ) < 1e-10:
            raise ValueError(f"Nearly singular Jacobian: det(J) = {detJ}")
        dN_xy   = np.linalg.solve(J, dN_nat.T).T   # 4×2 (dN/dx, dN/dy)

        B = np.zeros((3, 8))
        for i in range(4):
            B[0, 2*i    ] = dN_xy[i, 0]
            B[1, 2*i + 1] = dN_xy[i, 1]
            B[2, 2*i    ] = dN_xy[i, 1]
            B[2, 2*i + 1] = dN_xy[i, 0]
        return B, detJ

    # 8×8 element stiffness --------------------------------------
    def stiffness(self):
        Ke = np.zeros((8, 8))
        for xi,w_xi in zip(self.gp, self.w):
            for eta,w_eta in zip(self.gp, self.w):
                B, detJ = self._Bmatrix(xi, eta)
                Ke += B.T @ self.D @ B * detJ * w_xi * w_eta * self.t
        return Ke

    # stress and strain at centre (xi = eta = 0) ------------------
    def stress_strain(self, u_e):
        B, _   = self._Bmatrix(0, 0)
        eps    = B @ u_e
        sig    = self.D @ eps
        sig_vm = np.sqrt(sig[0]**2 + sig[1]**2 - sig[0]*sig[1] + 3*sig[2]**2)
        return eps, sig, sig_vm

# ----------------------------------------------------------------
# 3. Improved mesh with better hole handling
# ----------------------------------------------------------------
def rectangular_mesh_with_hole(L, H, R, nx, ny):
    """Generate a rectangular structured mesh with better hole handling"""
    # Create full rectangular grid first
    xs = np.linspace(-L/2, L/2, nx + 1)
    ys = np.linspace(-H/2, H/2, ny + 1)
    
    coords = []
    node_map = {}  # maps (i,j) to node index
    nid = 0
    
    # Create nodes, but mark those inside hole
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            coords.append([x, y])
            node_map[(i, j)] = nid
            nid += 1
    
    coords = np.array(coords)
    
    # Create elements, skipping those that intersect the hole
    elements = []
    hole_center = np.array([0.0, 0.0])
    
    for j in range(ny):
        for i in range(nx):
            # Get the 4 corner nodes of this element
            nodes = [
                node_map[(i, j)],
                node_map[(i+1, j)],
                node_map[(i+1, j+1)],
                node_map[(i, j+1)]
            ]
            
            # Check if any corner is inside the hole (with small buffer)
            element_coords = coords[nodes]
            distances = np.linalg.norm(element_coords - hole_center, axis=1)
            
            # Only keep element if all corners are outside hole
            if np.all(distances > R * 0.9):
                elements.append(nodes)
    
    # Remove unused nodes and renumber
    used_nodes = set()
    for elem in elements:
        used_nodes.update(elem)
    
    used_nodes = sorted(used_nodes)
    old_to_new = {old: new for new, old in enumerate(used_nodes)}
    
    new_coords = coords[used_nodes]
    new_elements = [[old_to_new[n] for n in elem] for elem in elements]
    
    return new_coords, np.array(new_elements, dtype=int)

# ----------------------------------------------------------------
# 4. Global assembler and solver
# ----------------------------------------------------------------
class PlateWithHoleModel:
    def __init__(self, L=0.2, H=0.1, R=0.02,
                 nx=40, ny=20,
                 E=210e9, nu=0.3, t=1e-3,
                 sigma0=100e6):
        self.L, self.H, self.R = L, H, R
        self.nx, self.ny = nx, ny
        self.mat = Material(E, nu)
        self.t   = t
        self.sigma0 = sigma0

        # mesh -------------------------------------------------------------
        self.xy, conn = rectangular_mesh_with_hole(L, H, R, nx, ny)
        self.nnode = self.xy.shape[0]
        self.ndof  = 2*self.nnode
        
        print(f"Generated mesh: {self.nnode} nodes, {len(conn)} elements")
        
        self.elements = [Q4Element(conn[e],
                                   self.xy[conn[e]],
                                   self.mat, t)
                         for e in range(len(conn))]
        
        # BC sets ----------------------------------------------------------
        self.fixed_dofs = self._get_boundary_conditions()
        self.loads      = self._right_edge_traction()

    def _get_boundary_conditions(self):
        """Better boundary condition setup"""
        tol = 1e-10
        fixed = set()
        
        # Fix x-displacement on left edge
        left_nodes = [i for i, (x, y) in enumerate(self.xy) 
                     if abs(x + self.L/2) < tol]
        for n in left_nodes:
            fixed.add(2*n)  # x-displacement
        
        # Fix one point completely to prevent rigid body motion
        if left_nodes:
            # Pin the bottom-most left node in y as well
            bottom_left = min(left_nodes, key=lambda i: self.xy[i, 1])
            fixed.add(2*bottom_left + 1)  # y-displacement
        
        print(f"Applied {len(fixed)} boundary condition constraints")
        return fixed

    def _right_edge_traction(self):
        """Apply traction on right edge"""
        tol = 1e-10
        edge_nodes = [i for i, (x, y) in enumerate(self.xy) 
                     if abs(x - self.L/2) < tol]
        
        if not edge_nodes:
            raise ValueError("No nodes found on right edge")
        
        # Sort by y-coordinate to apply proper distribution
        edge_nodes.sort(key=lambda i: self.xy[i, 1])
        
        force_total = self.sigma0 * self.H * self.t
        f_per_node = force_total / len(edge_nodes)
        
        loads = {}
        for n in edge_nodes:
            loads[2*n] = f_per_node  # x-direction force
        
        print(f"Applied loads to {len(edge_nodes)} nodes on right edge")
        return loads

    def assemble_K(self):
        """Assemble global stiffness matrix"""
        K = np.zeros((self.ndof, self.ndof))
        
        for el in self.elements:
            try:
                Ke = el.stiffness()
                dof = np.hstack([[2*n, 2*n+1] for n in el.nid])
                K[np.ix_(dof, dof)] += Ke
            except ValueError as e:
                print(f"Warning: Skipping element due to {e}")
                continue
        
        self.K = K
        
        # Check for zero diagonal entries (indicates problems)
        zero_diag = np.where(np.abs(np.diag(K)) < 1e-12)[0]
        if len(zero_diag) > 0:
            print(f"Warning: {len(zero_diag)} zero diagonal entries in stiffness matrix")

    def solve(self):
        """Solve the system with improved boundary condition application"""
        self.assemble_K()
        F = np.zeros(self.ndof)
        
        # Apply loads
        for dof, val in self.loads.items():
            F[dof] = val

        # Apply boundary conditions using elimination method
        free_dofs = [i for i in range(self.ndof) if i not in self.fixed_dofs]
        
        if len(free_dofs) == 0:
            raise ValueError("All DOFs are constrained - system over-constrained")
        
        # Extract free system
        K_ff = self.K[np.ix_(free_dofs, free_dofs)]
        F_f = F[free_dofs]
        
        # Check condition number
        cond = np.linalg.cond(K_ff)
        print(f"Condition number of free system: {cond:.2e}")
        
        if cond > 1e12:
            print("Warning: System may be poorly conditioned")
        
        # Solve free system
        try:
            u_f = np.linalg.solve(K_ff, F_f)
        except np.linalg.LinAlgError:
            # Try with regularization
            print("Adding regularization...")
            reg = 1e-10 * np.trace(K_ff) / len(free_dofs)
            K_ff += reg * np.eye(len(free_dofs))
            u_f = np.linalg.solve(K_ff, F_f)
        
        # Reconstruct full displacement vector
        self.u = np.zeros(self.ndof)
        self.u[free_dofs] = u_f
        # Fixed DOFs remain zero (already initialized)

    def postprocess(self):
        """Post-process results"""
        vm = []
        sig_x = []
        centroids = []
        
        for el in self.elements:
            try:
                dof = np.hstack([[2*n, 2*n+1] for n in el.nid])
                eps, sig, s_vm = el.stress_strain(self.u[dof])
                vm.append(s_vm)
                sig_x.append(sig[0])
                centroids.append(el.xy.mean(axis=0))
            except:
                # Skip problematic elements
                continue
        
        self.vm = np.array(vm)
        self.sig_x = np.array(sig_x)
        self.centroids = np.array(centroids)
        
        # SCF = max σ_xx / nominal (σ0)
        if len(self.sig_x) > 0:
            self.SCF = self.sig_x.max() / self.sigma0
        else:
            self.SCF = 0.0

    def plot_vm(self):
        """Plot von Mises stress contour"""
        if len(self.centroids) == 0:
            print("No valid stress data to plot")
            return
            
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Create contour plot
        tri = ax.tricontourf(self.centroids[:, 0], self.centroids[:, 1], 
                            self.vm/1e6, levels=20, cmap='viridis')
        
        # Add colorbar
        cbar = plt.colorbar(tri, ax=ax)
        cbar.set_label('von Mises Stress [MPa]')
        
        # Draw hole boundary
        theta = np.linspace(0, 2*np.pi, 100)
        hole_x = self.R * np.cos(theta)
        hole_y = self.R * np.sin(theta)
        ax.plot(hole_x, hole_y, 'w-', linewidth=2, label='Hole boundary')
        
        # Formatting
        ax.set_aspect('equal')
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title('von Mises Stress Distribution')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()

    def plot_deformed_shape(self, scale=1000):
        """Plot deformed shape"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Original shape
        ax.scatter(self.xy[:, 0], self.xy[:, 1], c='lightgray', s=1, alpha=0.5, label='Original')
        
        # Deformed shape
        u_x = self.u[0::2]
        u_y = self.u[1::2]
        deformed_x = self.xy[:, 0] + scale * u_x
        deformed_y = self.xy[:, 1] + scale * u_y
        
        ax.scatter(deformed_x, deformed_y, c='red', s=1, alpha=0.7, label=f'Deformed ({scale}x)')
        
        # Hole boundary (original and deformed)
        theta = np.linspace(0, 2*np.pi, 100)
        ax.plot(self.R * np.cos(theta), self.R * np.sin(theta), 'k-', linewidth=2)
        
        ax.set_aspect('equal')
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title(f'Deformed Shape (Scale: {scale}x)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()

# ----------------------------------------------------------------
# 5. Simple driver
# ----------------------------------------------------------------
if __name__ == '__main__':
    # create and solve model -----------------------------------------------
    model = PlateWithHoleModel(L=0.4,  H=0.2,   R=0.02,     # geometry [m] - larger plate
                               nx=60,  ny=30,               # mesh density - finer mesh
                               E=210e9, nu=0.3, t=1.0e-3,   # material/thk
                               sigma0=100e6)                # applied stress
    
    print('\nAssembling and solving system...')
    try:
        model.solve()
        model.postprocess()
        
        # Report results
        print('\n' + '='*60)
        print('  Plate with Central Hole: FEM Results')
        print('='*60)
        print(f'Geometry       : {model.L:.3f} × {model.H:.3f} m, R = {model.R:.3f} m')
        print(f'Nodes          : {model.nnode:,}')
        print(f'Elements       : {len(model.elements):,}')
        print(f'DOFs           : {model.ndof:,}')
        print(f'Constrained    : {len(model.fixed_dofs)}')
        print('-'*60)
        print(f'Max |u|        : {np.abs(model.u).max()*1e6:9.3f} μm')
        print(f'Max σ_xx       : {model.sig_x.max()/1e6:9.2f} MPa')
        print(f'Nominal σ_xx   : {model.sigma0/1e6:9.2f} MPa')
        print(f'SCF (σ_max/σ_0): {model.SCF:9.2f}')
        print(f'Theory (Kirsch): {3.00:9.2f}')
        print('='*60)
        
        # Generate plots
        model.plot_vm()
        model.plot_deformed_shape()
        
    except Exception as e:
        print(f"Error during solution: {e}")
        import traceback
        traceback.print_exc()